import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.interfaces.decision_web import create_decision_app


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    data = tmp_path / "data"
    out = data / "daily" / "2026-09-23"
    out.mkdir(parents=True)
    brief = {"date": "2026-09-23", "jczq": {"matches": [], "counts": {}},
             "zucai": {"issue": None}, "rsi": None, "factors": [], "errors": []}
    (out / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    app = create_decision_app(output_dir=data / "jczq", data_dir=data,
                              launchctl=lambda: "-\t0\tcom.nutmeg.rsi.loop\n")
    return TestClient(app), data


def test_day_page_and_api(tmp_path: Path):
    client, _ = _client(tmp_path)
    page = client.get("/day/2026-09-23")
    assert page.status_code == 200
    assert "当日" in page.text and "/static/decision/day.js" in page.text
    assert "<form" not in page.text
    api = client.get("/api/day/2026-09-23")
    assert api.status_code == 200
    body = api.json()
    assert body["brief"]["date"] == "2026-09-23" and isinstance(body["launchd"], list)
    assert "缺 decisions.json" in body["errors"]


def test_day_root_redirects_to_today(tmp_path: Path):
    client, _ = _client(tmp_path)
    r = client.get("/day", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].startswith("/day/20")


def test_day_note_appends_discussion(tmp_path: Path):
    client, data = _client(tmp_path)
    r = client.post("/action/day-note",
                    json={"date": "2026-09-23", "obj": "周三001", "text": "想双选"})
    assert r.status_code == 200 and r.json()["seq"] == 1
    path = data / "daily" / "2026-09-23" / "discussion.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["who"] == "jun"
    assert client.get("/api/day/2026-09-23").json()["discussion"][0]["text"] == "想双选"


def test_day_note_rejects_empty_text(tmp_path: Path):
    client, _ = _client(tmp_path)
    r = client.post("/action/day-note", json={"date": "2026-09-23", "text": "  "})
    assert r.status_code == 400


def test_day_page_has_every_block_and_links_back(tmp_path: Path):
    client, _ = _client(tmp_path)
    html = client.get("/day/2026-09-23").text
    for block in ("day-status", "day-retro", "day-jczq", "day-zucai", "day-rsi",
                  "day-decisions", "day-session", "day-talk"):
        assert f'id="{block}"' in html
    assert "/static/decision/day.css" in html
    assert 'href="/observe"' in html and 'href="/ledger"' in html


def test_workbench_topbar_links_to_day(tmp_path: Path):
    client, _ = _client(tmp_path)
    assert 'href="/day"' in client.get("/").text


# ── 第 6 阶段 Task 6.1：导航外壳 + 空仓登记 + 今天页数据 ─────────────────────
from datetime import datetime, timedelta, timezone  # noqa: E402

from markupsafe import escape  # noqa: E402

_BJ = timezone(timedelta(hours=8))
_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=_BJ)
_TODAY = "2026-10-28"


def _shell_client(tmp_path: Path) -> tuple[TestClient, Path]:
    """在售期 26152（停售 22:00）+ 旁车 + 当日 brief；钟固定在 _NOW。"""
    data = tmp_path / "data"
    z = data / "zucai"
    z.mkdir(parents=True)
    (data / "jczq").mkdir()
    matches = [{"match_no": str(i), "home_team": f"甲{i}", "away_team": f"乙{i}",
                "kickoff_bj": "2026-10-29T02:45:00+08:00"} for i in range(1, 15)]
    (z / "26152-issue.json").write_text(json.dumps(
        {"issue_id": "26152", "sale_deadline": "2026-10-28T22:00:00+08:00",
         "matches": matches}, ensure_ascii=False), encoding="utf-8")
    tiers = ["A", "B", "b", "C", "C", "D", "B", "C", "D", "C", "D", "D", "C", "D"]
    rows = [{"no": str(i), "tier": t, "k": None if t == "D" else 3,
             "n": None if t == "D" else 6, "default": "31"}
            for i, t in enumerate(tiers, start=1)]
    (z / "26152-packet.json").write_text(json.dumps({
        "issue": "26152", "rows": rows,
        "default": {"action": "空仓", "reason": "许可胆 0"},
        "main_shape": {"label": "W2 2单7双", "faces": {"1": "3"}, "price": 256, "p": 0.0741,
                       "note": "字典主形"},
        "alternatives": [{"label": "丢光C档", "role": "丢光C档", "faces": {"1": "3"},
                          "price": 162, "p": 0.101}]}, ensure_ascii=False), encoding="utf-8")
    out = data / "daily" / _TODAY
    out.mkdir(parents=True)
    (out / "brief.json").write_text(json.dumps({"date": _TODAY}), encoding="utf-8")
    app = create_decision_app(output_dir=data / "jczq", data_dir=data, launchctl=lambda: "")
    app.state.now = lambda: _NOW
    return TestClient(app), data


def test_three_pages_carry_the_nav_with_active_issue_links(tmp_path: Path):
    client, _ = _shell_client(tmp_path)
    for url in (f"/day/{_TODAY}", "/issue/26152", f"/jczq/{_TODAY}"):
        html = client.get(url).text
        assert 'class="nm-nav"' in html, url
        assert 'href="/issue/26152"' in html and "停售 22:00" in html, url
        assert 'href="/jczq"' in html and 'href="/ledger"' in html, url
        assert "/static/decision/shell.css" in html, url


def test_nav_brake_title_is_the_status_line(tmp_path: Path):
    from nutmeg.decision.bankroll import status_line
    from nutmeg.decision.precheck import month_brake

    client, data = _shell_client(tmp_path)
    line = status_line(month_brake(data, _TODAY))
    assert f'title="{escape(line)}"' in client.get(f"/day/{_TODAY}").text
    shell = client.get("/api/shell").json()
    assert shell["brake"]["line"] == line and shell["today"] == _TODAY
    assert shell["issues"] == [{"issue": "26152", "deadline": "2026-10-28T22:00:00+08:00",
                                "close": "22:00"}]
    assert shell["errors"] == []


def test_action_pass_writes_once_then_reports_existed(tmp_path: Path):
    client, data = _shell_client(tmp_path)
    first = client.post("/action/pass", json={"channel": "zucai", "target": "26152",
                                              "reason": ""}).json()
    assert first["ok"] is True and first["existed"] is False
    assert first["pass"]["reason"] == "同意机器默认空仓"
    again = client.post("/action/pass", json={"channel": "zucai", "target": "26152",
                                              "reason": "另一句"}).json()
    assert again["existed"] is True and again["pass"] == first["pass"]
    lines = (data / "daily" / _TODAY / "passes.jsonl").read_text("utf-8").splitlines()
    assert len(lines) == 1
    jczq = client.post("/action/pass", json={"channel": "jczq", "target": _TODAY})
    assert jczq.status_code == 200 and jczq.json()["existed"] is False


def test_action_pass_rejects_targets_not_on_sale(tmp_path: Path):
    client, _ = _shell_client(tmp_path)
    assert client.post("/action/pass", json={"channel": "zucai",
                                             "target": "26140"}).status_code == 400
    assert client.post("/action/pass", json={"channel": "jczq",
                                             "target": "2026-13-40"}).status_code == 400
    assert client.post("/action/pass", json={"channel": "x",
                                             "target": "26152"}).status_code == 400


def test_api_day_decisions_carry_href_and_pass_target_and_close_on_pass(tmp_path: Path):
    client, _ = _shell_client(tmp_path)
    body = client.get(f"/api/day/{_TODAY}").json()
    z = next(d for d in body["decisions"] if d["kind"] == "register_zucai")
    assert z["href"] == "/issue/26152" and z["status"] == "open"
    assert z["pass_target"] == {"channel": "zucai", "target": "26152"}
    assert body["shell"]["issues"][0]["issue"] == "26152" and body["passes"] == []
    client.post("/action/pass", json={"channel": "zucai", "target": "26152", "reason": "空"})
    body = client.get(f"/api/day/{_TODAY}").json()
    z = next(d for d in body["decisions"] if d["kind"] == "register_zucai")
    assert z["status"] == "done" and z["subject"] == "足彩 26152 空仓·已登记 12:00"
    assert z["pass_target"] is None and body["passes"][0]["target"] == "26152"


def test_glance_tier_counts_and_license_rows_match_the_sidecar(tmp_path: Path):
    client, _ = _shell_client(tmp_path)
    g = client.get(f"/api/day/{_TODAY}").json()["glance"]
    assert [x["issue"] for x in g] == ["26152"]
    g = g[0]
    assert g["tiers"] == {"A": 1, "B": 2, "b": 1, "C": 5, "D": 5}
    assert g["license_rows"] == [
        {"no": "1", "name": "甲1-乙1", "tier": "A", "k": 3, "n": 6},
        {"no": "2", "name": "甲2-乙2", "tier": "B", "k": 3, "n": 6},
        {"no": "3", "name": "甲3-乙3", "tier": "b", "k": 3, "n": 6},
        {"no": "7", "name": "甲7-乙7", "tier": "B", "k": 3, "n": 6}]
    assert g["default"] == {"action": "空仓", "reason": "许可胆 0"}
    assert g["main_shape"] == {"label": "W2 2单7双", "price": 256, "p": 0.0741,
                               "note": "字典主形"}
    assert g["alternatives"] == [{"label": "丢光C档", "role": "丢光C档", "price": 162,
                                  "p": 0.101, "note": None}]
    assert g["deadline"] == "2026-10-28T22:00:00+08:00" and g["errors"] == []


def test_glance_missing_sidecar_is_an_error_not_a_500(tmp_path: Path):
    client, data = _shell_client(tmp_path)
    (data / "zucai" / "26152-packet.json").unlink()
    r = client.get(f"/api/day/{_TODAY}")
    assert r.status_code == 200
    g = r.json()["glance"][0]
    assert g["tiers"] == {"A": 0, "B": 0, "b": 0, "C": 0, "D": 0}
    assert any("26152-packet.json" in e for e in g["errors"])
