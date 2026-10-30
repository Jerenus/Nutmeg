"""纠正账页（2026-10-30 产品形态 Task 10.2）：页面带导航、接口给 rows/summary/labels、页面只许确认 /
不改两种状态、期页接口带本期纠正。"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.decision import corrections as cx
from nutmeg.interfaces.decision_web import create_decision_app


def _client(data: Path) -> TestClient:
    (data / "jczq").mkdir(parents=True, exist_ok=True)
    return TestClient(create_decision_app(output_dir=data / "jczq", data_dir=data,
                                          launchctl=lambda: ""))


def _seed(data: Path) -> dict[str, str]:
    data.mkdir(parents=True, exist_ok=True)
    return {
        "m3": cx.record(data, obj="issue:26151/m3", old="缺阵", new="首发", kind="premise",
                        found_by="result", pile="研究前提错", at="2026-10-28T09:44:00+08:00"),
        "slip": cx.record(data, obj="slip:26151-T1", old="已购", new="试玩",
                          kind="transcription", found_by="jun", status="written",
                          at="2026-10-28T08:00:00+08:00"),
        "other": cx.record(data, obj="issue:26150/m1", old="a", new="b", kind="data",
                           found_by="official", status="written", at="2026-10-27T08:00:00+08:00"),
    }


def test_corrections_page_renders_with_nav_link_and_badge(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    page = _client(data).get("/corrections")
    assert page.status_code == 200
    assert "/static/decision/corrections.js" in page.text
    assert '<a href="/corrections" aria-current="page">纠正' in page.text
    assert 'class="nm-badge"' in page.text and ">1</span>" in page.text   # 一条草稿


def test_nav_has_no_badge_without_drafts(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    html = _client(data).get("/lab").text
    assert 'href="/corrections">纠正</a>' in html and "nm-badge" not in html
    order = [html.index(f'href="/{p}"') for p in ("ledger", "corrections", "lab")]
    assert order == sorted(order)


def test_corrections_api_rows_summary_labels_and_filters(tmp_path):
    data = tmp_path / "data"
    ids = _seed(data)
    c = _client(data)
    body = c.get("/api/corrections").json()
    assert body["errors"] == []
    assert [r["id"] for r in body["rows"]] == [ids["m3"], ids["slip"], ids["other"]]
    assert body["summary"]["drafts"] == 1
    assert body["summary"]["piles"] == [{"pile": "研究前提错", "n": 1, "dates": ["2026-10-28"],
                                         "open": 1}]
    assert set(body["labels"]) == {"kinds", "found_by", "dests", "statuses"}
    assert body["labels"]["kinds"]["premise"] == "研究前提"
    only = c.get("/api/corrections", params={"obj": "issue:26151"}).json()
    assert [r["id"] for r in only["rows"]] == [ids["m3"]]
    assert only["summary"]["by_kind"] == {"premise": 1, "transcription": 1, "data": 1}  # 全账
    written = c.get("/api/corrections", params={"status": "written"}).json()["rows"]
    assert [r["id"] for r in written] == [ids["slip"], ids["other"]]


def test_corrections_api_bad_ledger_lines_do_not_500(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / cx.LEDGER).write_text("不是 json\n" + json.dumps({"op": "status", "id": "C-x"}) + "\n",
                                  encoding="utf-8")
    body = _client(data).get("/api/corrections").json()
    assert body["rows"] == [] and body["summary"]["drafts"] == 0


def test_status_post_allows_confirm_and_dismiss_only(tmp_path):
    data = tmp_path / "data"
    ids = _seed(data)
    c = _client(data)
    r = c.post(f"/action/correction/{ids['m3']}/status", json={"status": "confirmed", "note": "对"})
    assert r.status_code == 200 and r.json()["ok"]
    (row,) = [x for x in cx.load(data) if x["id"] == ids["m3"]]
    assert row["status"] == "confirmed" and row["history"][-1]["by"] == "jun"
    assert c.post(f"/action/correction/{ids['m3']}/status",
                  json={"status": "dismissed"}).status_code == 200
    for bad in ("written", "nowhere", "draft", ""):
        assert c.post(f"/action/correction/{ids['m3']}/status",
                      json={"status": bad}).status_code == 400
    assert c.post("/action/correction/C-deadbeef/status",
                  json={"status": "confirmed"}).status_code == 404


def test_issue_api_carries_issue_and_slip_corrections(tmp_path):
    data = tmp_path / "data"
    ids = _seed(data)
    (data / "zucai").mkdir()
    body = _client(data).get("/api/issue/26151").json()
    assert [c["id"] for c in body["corrections"]] == [ids["m3"], ids["slip"]]
    assert set(body["corrections"][0]) == {"id", "at", "obj", "old", "new", "kind", "status"}


def test_corrections_static_assets_served(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    c = _client(data)
    assert c.get("/static/decision/corrections.js").status_code == 200
    assert c.get("/static/decision/corrections.css").status_code == 200
