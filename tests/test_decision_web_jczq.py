"""竞彩当日板（2026-10-28 产品形态第 5 阶段 Task 5.1）：板面 API、服务端组腿预审、登记 J<n>。"""
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nutmeg.decision.betslip import load_slips, next_jczq_slip_id, next_slip_id
from nutmeg.decision.bj_time import BJ
from nutmeg.interfaces.decision_web import create_decision_app

DAY = "2026-10-25"
NOW = datetime(2026, 10, 25, 11, 30, tzinfo=BJ)
SP = {"周日001": ("1.50", "4.00", "5.50"), "周日002": ("1.85", "3.40", "3.90"),
      "周日003": ("2.60", "3.10", "2.55"), "周日004": ("2.00", "3.20", "3.30")}
FAIR = {"周日001": {"home": 0.62, "draw": 0.22, "away": 0.16},
        "周日002": {"home": 0.50, "draw": 0.27, "away": 0.23},
        "周日003": {"home": 0.36, "draw": 0.30, "away": 0.34},
        "周日004": {"home": 0.45, "draw": 0.28, "away": 0.27}}


def _match(code: str, *, time: str, single: int, had=None, status="Selling") -> dict:
    h, d, a = had or SP[code]
    return {"matchStatus": status, "businessDate": DAY, "matchNumStr": code,
            "matchDate": DAY, "matchTime": time,
            "homeTeamAbbName": f"主{code[-1]}", "awayTeamAbbName": f"客{code[-1]}",
            "leagueAbbName": "英超",
            "had": {"h": h, "d": d, "a": a, "goalLine": ""},
            "hhad": {"h": "4.10", "d": "3.70", "a": "1.62", "goalLine": "-1",
                     "goalLineValue": "-1.00"},
            "poolList": [{"poolCode": "HAD", "single": single, "allUp": 1},
                         {"poolCode": "HHAD", "single": 0, "allUp": 1}]}


def _data(tmp_path: Path, *, extra: int = 0, formulas=("Single", "2x1", "3x1")) -> Path:
    data = tmp_path / "data"
    day_dir = data / "jczq" / "daily" / DAY
    day_dir.mkdir(parents=True)
    rows = [_match("周日001", time="11:00:00", single=1),        # 已开球（NOW 11:30）
            _match("周日002", time="19:30:00", single=1),
            _match("周日003", time="20:00:00", single=0),
            _match("周日004", time="21:00:00", single=0, status="Closed")]
    fair = dict(FAIR)
    for i in range(extra):                                       # >8 腿测试用的在售场
        code = f"周日{100 + i:03d}"
        rows.append(_match(code, time="22:00:00", single=0, had=("2.00", "3.20", "3.30")))
        fair[code] = {"home": 0.45, "draw": 0.28, "away": 0.27}
    doc = {"matchInfoList": [{"businessDate": DAY, "subMatchList": rows}],
           "allUpList": {"HAD": [{"formula": f} for f in formulas]}}
    (day_dir / "sporttery_markets.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                    encoding="utf-8")
    legs = {code: {"match_id": f"m-{code}", "name": f"主{code[-1]}-客{code[-1]}",
                   "kickoff_bj": f"{DAY}T{r['matchTime'][:5]}:00+08:00", "fair": fair[code],
                   "stance": {"face": "3", "faces": "31", "structure": "double"}
                   if code == "周日002" else None}
            for code, r in ((r["matchNumStr"], r) for r in rows)}
    (day_dir / "jczq-legs-base.json").write_text(json.dumps({"day": DAY, "legs": legs},
                                                            ensure_ascii=False), encoding="utf-8")
    return data


def _client(data: Path) -> TestClient:
    app = create_decision_app(output_dir=data / "jczq", data_dir=data, launchctl=lambda: "")
    app.state.now = lambda: NOW
    return TestClient(app)


def test_board_rows_selectable_and_return_per_yuan(tmp_path):
    body = _client(_data(tmp_path)).get(f"/api/jczq/{DAY}").json()
    rows = {r["code"]: r for r in body["rows"]}
    assert set(rows) == {"周日001", "周日002", "周日003", "周日004"}
    assert [r["code"] for r in body["rows"] if r["selectable"]] == ["周日002", "周日003"]
    assert rows["周日001"]["kicked"] is True and rows["周日001"]["selectable"] is False
    assert rows["周日004"]["selectable"] is False                 # 停售
    r2 = rows["周日002"]
    assert r2["sp"] == {"3": 1.85, "1": 3.4, "0": 3.9}
    assert r2["fair"] == {"3": 0.50, "1": 0.27, "0": 0.23}
    assert r2["ret"]["3"] == pytest.approx(0.50 * 1.85, abs=1e-3)
    assert r2["ret"]["0"] == pytest.approx(0.23 * 3.9, abs=1e-3)
    assert r2["single"] is True and rows["周日003"]["single"] is False
    assert r2["hhad"]["line"] == -1.0
    assert r2["stance"].startswith("双")
    assert body["allup_had"] == ["2x1", "3x1", "Single"]
    assert {"line", "room", "tripped"} <= set(body["brake"])
    assert body["counts"]["rows"] == 4 and body["counts"]["selectable"] == 2
    assert body["errors"] == []


def test_board_without_snapshot_reports_errors_not_500(tmp_path):
    data = tmp_path / "data"
    (data / "jczq").mkdir(parents=True)
    resp = _client(data).get(f"/api/jczq/{DAY}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == [] and body["errors"] and "快照" in body["errors"][0]


def test_bad_day_is_400_and_redirect_and_shell(tmp_path):
    c = _client(_data(tmp_path))
    assert c.get("/api/jczq/2026-1025").status_code == 400
    assert c.get("/jczq/20261025").status_code == 400
    redirect = c.get("/jczq", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"].startswith("/jczq/20")
    page = c.get(f"/jczq/{DAY}")
    assert page.status_code == 200
    assert "/static/decision/jczq.js" in page.text and f'data-day="{DAY}"' in page.text


def test_precheck_two_leg_parlay_matches_direct_precheck(tmp_path):
    from nutmeg.decision.precheck import build_slip, precheck

    data = _data(tmp_path)
    body = _client(data).post(f"/api/jczq/{DAY}/precheck", json={
        "picks": {"周日002": "3", "周日003": "10"}, "multiplier": 5}).json()
    assert body["ok"] is True, body
    legs = [{"key": "周日002", "name": "主2-客2", "market": "had", "selections": ["home"],
             "odds": [1.85], "fair": FAIR["周日002"]},
            {"key": "周日003", "name": "主3-客3", "market": "had", "selections": ["draw", "away"],
             "odds": [3.1, 2.55], "fair": FAIR["周日003"]}]
    direct = precheck(build_slip(slip_id="preview", channel="jczq", placed_at=DAY, legs=legs,
                                 combo="2", multiplier=5, data_dir=data), data, log=False)
    assert body["ratio"] == direct["ratio"] and body["ratio"] is not None
    assert body["notes"] == 2 and body["stake"] == 20 and body["combo"] == "2串1"
    assert body["p"] == pytest.approx(0.50 * 0.64, abs=1e-6)
    assert body["max_payout"] == pytest.approx(2 * 5 * 1.85 * 3.1, abs=0.01)
    assert body["legs"] == [{"code": "周日002", "name": "主2-客2", "faces": "3", "odds": [1.85]},
                            {"code": "周日003", "name": "主3-客3", "faces": "10",
                             "odds": [3.1, 2.55]}]
    assert {"verdicts", "discipline", "brake_line", "notes"} <= set(body)


def test_precheck_rejections(tmp_path):
    c = _client(_data(tmp_path))

    def err(picks):
        out = c.post(f"/api/jczq/{DAY}/precheck", json={"picks": picks}).json()
        assert out["ok"] is False, out
        return out["error"]

    assert "单关" in err({"周日003": "3"})                     # 单关未开的 1 腿
    assert "开球" in err({"周日001": "3", "周日002": "3"})      # 已开球
    assert "周日004" in err({"周日004": "3", "周日002": "3"})   # 停售
    assert "周日999" in err({"周日999": "3", "周日002": "3"})   # 板上没有
    assert err({"周日002": "x", "周日003": "3"})                # 面不合法
    assert err({})                                               # 没选
    ok = c.post(f"/api/jczq/{DAY}/precheck", json={"picks": {"周日002": "3"}}).json()
    assert ok["ok"] is True and ok["combo"] == "单关" and ok["stake"] == 2


def test_precheck_rejects_more_than_eight_legs_and_unsold_parlay(tmp_path):
    c = _client(_data(tmp_path, extra=9))
    picks = {f"周日{100 + i:03d}": "3" for i in range(9)}
    out = c.post(f"/api/jczq/{DAY}/precheck", json={"picks": picks}).json()
    assert out["ok"] is False and "8" in out["error"]
    four = dict(list(picks.items())[:4])                        # allup 只有 2x1/3x1
    out = c.post(f"/api/jczq/{DAY}/precheck", json={"picks": four}).json()
    assert out["ok"] is False and "4串1" in out["error"]


def test_register_twice_assigns_j1_j2_purchased_and_slip_text(tmp_path):
    data = _data(tmp_path)
    c = _client(data)
    payload = {"picks": {"周日002": "3", "周日003": "10"}, "multiplier": 5, "scheme_no": "500-1"}
    first = c.post(f"/action/jczq/{DAY}/register", json=payload).json()
    second = c.post(f"/action/jczq/{DAY}/register", json=payload).json()
    assert first["ok"] is True, first
    assert first["slip_id"] == "20261025-J1" and second["slip_id"] == "20261025-J2"
    slips = {s.slip_id: s for s in load_slips(data, channel="jczq")}
    assert set(slips) == {"20261025-J1", "20261025-J2"}
    s1 = slips["20261025-J1"]
    assert s1.purchased is True and s1.placed_at == DAY and s1.combo_sizes == (2,)
    assert s1.scheme_no == "500-1" and s1.multiplier == 5
    assert [leg.odds for leg in s1.legs] == [(1.85,), (3.1, 2.55)]
    assert s1.diagnosis.get("review")                           # 审票随票入账
    lines = first["slip_text"].splitlines()
    assert lines[0] == "周日002 主2-客2 胜平负 胜 @1.85"
    assert lines[1] == "周日003 主3-客3 胜平负 平/负 @3.10/2.55"
    assert lines[2] == "2串1 · 2 注 · 5 倍 · ¥20"
    assert {"codes", "vetoed", "after_kickoff", "brake_line", "summary"} <= set(first)


def test_register_rejects_bad_deviation_before_writing(tmp_path):
    data = _data(tmp_path)
    out = _client(data).post(f"/action/jczq/{DAY}/register", json={
        "picks": {"周日002": "3", "周日003": "3"}, "deviation": "瞎猜"}).json()
    assert out["ok"] is False and load_slips(data) == []


def test_next_jczq_slip_id_ignores_other_days_and_zucai(tmp_path):
    rows = [{"slip_id": "20261025-J1", "channel": "jczq", "placed_at": DAY, "legs": []},
            {"slip_id": "20261025-J3", "channel": "jczq", "placed_at": DAY, "legs": []},
            {"slip_id": "20261024-J7", "channel": "jczq", "placed_at": "2026-10-24", "legs": []},
            {"slip_id": "26150-T2", "channel": "renjiu", "issue": "26150", "legs": []}]
    (tmp_path / "betslips.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert next_jczq_slip_id(tmp_path, DAY) == "20261025-J4"
    assert next_jczq_slip_id(tmp_path, "2026-10-26") == "20261026-J1"
    assert next_slip_id(tmp_path, "26150") == "26150-T3"
