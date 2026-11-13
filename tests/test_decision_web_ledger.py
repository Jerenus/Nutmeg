"""账房页接口（2026-10-28 产品形态第 7 阶段 Task 7.1）：主接口不跑回放、三本账在、坏月份 400、
初稿账按需且命中缓存。"""
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nutmeg.decision.account import draft_board as _real_draft_board
from nutmeg.decision.bj_time import BJ
from nutmeg.interfaces.decision_web import create_decision_app

_NOW = datetime(2026, 10, 28, 9, 0, tzinfo=BJ)
NINE = {str(i): "3" for i in range(1, 10)}


def _boom(*_a, **_k):
    raise AssertionError("主接口不该跑 gym 回放")


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    data = tmp_path / "data"
    (data / "zucai").mkdir(parents=True)
    (data / "jczq").mkdir()
    for issue, deadline in (("26145", "2026-10-19 21:30"), ("26150", "2026-10-25 21:30"),
                            ("26134", "2026-09-28 22:00")):
        (data / "zucai" / f"{issue}-issue.json").write_text(
            json.dumps({"issue_id": issue, "sale_deadline": deadline}), encoding="utf-8")
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "26134": {"net": -539.0, "stake": 756, "payout": 217.0},
        "jczq-20261017": {"net": -140.98, "stake": 198, "payout": 57.02,
                          "slips": [{"id": "20261017-J1", "stake": 198, "payout": 57.02}]},
        "jczq-20261018": {"net": 0, "stake": 0, "payout": 0, "slips": []},
        "26145": {"net": -384.0, "stake": 384, "payout": 0.0,
                  "slips": [{"id": "26145-T1", "stake": 384, "payout": 0.0}]},
    }}), encoding="utf-8")
    (data / "betslips.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"slip_id": "26150-T1", "channel": "renjiu", "placed_at": "2026-10-25", "purchased": True,
         "issue": "26150", "faces": NINE, "multiplier": 32, "legs": [],
         "deviation": "换 5 号", "deviation_after_kickoff": False},
    ]) + "\n", encoding="utf-8")
    (data / "zucai" / "26150-bridge.jsonl").write_text(json.dumps(
        {"at": "2026-10-25T20:00:00+08:00", "faces": {**NINE, "5": "1"}, "slip_id": "26150-B1",
         "channel": "renjiu", "diffs": []}) + "\n", encoding="utf-8")
    monkeypatch.setattr("nutmeg.decision.account.experiment_board", lambda _d: {})
    monkeypatch.setattr("nutmeg.decision.account.draft_board", _boom)
    monkeypatch.setattr("nutmeg.decision.account.rule_v3_board", _boom)
    monkeypatch.setattr("nutmeg.gym.run.run_gym", _boom)
    app = create_decision_app(output_dir=data / "jczq", data_dir=data, launchctl=lambda: "")
    app.state.now = lambda: _NOW
    return TestClient(app), data


def test_ledger_api_runs_no_replay_and_has_three_ledgers(client):
    tc, _ = client
    r = tc.get("/api/ledger/2026-10")
    assert r.status_code == 200
    body = r.json()
    assert body["errors"] == []
    assert body["month"] == "2026-10" and body["months"] == ["2026-10", "2026-09"]
    report = body["report"]
    assert report["net"] == -524.98 and "draft" not in report and "rule_v3" not in report
    assert report["pending"]["n"] == 1 and report["effective_net"] == -524.98 - 64
    # 三本账：理由账（月报）、选择账、桥后改动账
    assert report["deviations"]["by_reason"]["换 5 号"]["n"] == 1
    assert [row["issue"] for row in body["choices"]["rows"]] == ["26145", "26150"]
    [bridge] = body["bridges"]
    assert bridge["issue"] == "26150" and bridge["walked"] is True
    assert bridge["real"][0]["slip_id"] == "26150-T1" and bridge["real"][0]["changed"] == ["5"]
    curve = body["curve"]
    assert curve["points"][-1]["net"] == report["net"]
    assert curve["effective"] == {"day": "2026-10-28", "net": -588.98}
    assert body["issues"] == [{"issue": "26145", "stake": 384, "payout": 0.0, "net": -384.0,
                               "slips": 1}]
    assert body["jczq_days"] == [{"day": "2026-10-17", "stake": 198, "net": -140.98}]
    # 买前预审覆盖率随月报原样出（账房页单列一格）
    cov = report["preview_coverage"]
    assert cov["n"] == cov["covered"] + len(cov["missing"]) and cov["n"] >= 1


def test_ledger_block_failure_goes_to_errors_not_500(client, monkeypatch):
    tc, _ = client

    def bad(*_a, **_k):
        raise ValueError("choices exploded")

    monkeypatch.setattr("nutmeg.decision.choice_ledger.build_choices", bad)
    r = tc.get("/api/ledger/2026-10")
    assert r.status_code == 200
    assert any("choices exploded" in e for e in r.json()["errors"])
    assert r.json()["curve"]["points"]


def test_bad_month_is_400(client):
    tc, _ = client
    for url in ("/api/ledger/2026-13", "/api/ledger/202610", "/ledger/2026-1",
                "/api/ledger/oct/draft"):
        assert tc.get(url).status_code == 400, url


def test_ledger_root_redirects_and_page_carries_nav(client):
    tc, _ = client
    r = tc.get("/ledger", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/ledger/2026-10"
    html = tc.get("/ledger/2026-10").text
    assert 'id="ledger"' in html and 'data-month="2026-10"' in html
    assert '<a href="/ledger" aria-current="page">账房</a>' in html
    assert "/static/decision/ledger.js" in html and "/static/decision/shell.css" in html


def test_draft_is_on_demand_and_cached_until_the_ledgers_change(client, monkeypatch):
    tc, data = client
    calls = []

    def draft(_d, month):
        calls.append(month)
        return {"issues": 2, "real": {"label": "实际出票", "net": -384.0}}

    monkeypatch.setattr("nutmeg.decision.account.draft_board", draft)
    first = tc.get("/api/ledger/2026-10/draft").json()
    assert tc.get("/api/ledger/2026-10/draft").json() == first and calls == ["2026-10"]
    tc.get("/api/ledger/2026-09/draft")
    assert calls == ["2026-10", "2026-09"]
    sb = data / "scoreboard.json"
    sb.write_text(sb.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    import os
    os.utime(sb, ns=(sb.stat().st_atime_ns, sb.stat().st_mtime_ns + 10**9))
    tc.get("/api/ledger/2026-10/draft")
    assert calls == ["2026-10", "2026-09", "2026-10"]


def test_draft_failure_is_not_cached_and_not_500(client, monkeypatch):
    tc, _ = client
    r = tc.get("/api/ledger/2026-10/draft")          # fixture 里 draft_board 抛错
    assert r.status_code == 200 and "_error" in r.json()


def test_ledger_payout_sums_scoreboard_and_lists_entries_without_numbers(client):
    """返奖由服务端按记分牌 payout 加总（页面只做 返奖/投入 的展示）；缺投入或返奖的条目点名。"""
    tc, data = client
    assert tc.get("/api/ledger/2026-10").json()["payout"] == {"payout": 57.02, "missing": []}
    sb = data / "scoreboard.json"
    doc = json.loads(sb.read_text(encoding="utf-8"))
    doc["tickets"]["26150"] = {"net": -768.0, "stake": None, "payout": None}
    sb.write_text(json.dumps(doc), encoding="utf-8")
    body = tc.get("/api/ledger/2026-10").json()
    assert body["payout"] == {"payout": 57.02, "missing": ["26150"]}
    assert body["report"]["net"] == -524.98 - 768.0


def test_draft_carries_counterfactual_curve(client, monkeypatch):
    """Task 7.3：/draft 带逐期 by_issue 与反事实 curve（竞彩照实际、足彩换成机器初稿）。"""
    from types import SimpleNamespace

    tc, _ = client
    ledger = [{"issue": "26145", "key": "2026-10-19", "policy": "real", "net": -384.0},
              {"issue": "26145", "key": "2026-10-19", "policy": "zucai_draft", "net": 100.0}]
    monkeypatch.setattr("nutmeg.decision.account.draft_board", _real_draft_board)
    monkeypatch.setattr("nutmeg.gym.board.list_issues", lambda _d: ["26145", "26150"])
    monkeypatch.setattr("nutmeg.gym.run.run_gym",
                        lambda **_k: SimpleNamespace(ledger=ledger, per_policy={}))
    body = tc.get("/api/ledger/2026-10/draft").json()
    assert body["by_issue"][0] == {"issue": "26145", "day": "2026-10-19", "real": -384.0,
                                   "draft": 100.0}
    # 实际 10-17 −140.98、10-19 −524.98；26145 差额 +484
    assert body["curve"] == [{"day": "2026-10-17", "net": -140.98},
                             {"day": "2026-10-19", "net": -40.98},
                             {"day": "2026-10-25", "net": -40.98}]
