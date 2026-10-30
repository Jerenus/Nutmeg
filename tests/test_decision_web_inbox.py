"""待签收件箱页（2026-10-30 产品形态 Task 10.3）：页面带导航与角标、接口给 rows/summary/labels、
页面答复成功 / 400 / 404、RSI 开着的项可答。"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.decision import proposals as px
from nutmeg.interfaces.decision_web import create_decision_app


def _client(data: Path) -> TestClient:
    (data / "jczq").mkdir(parents=True, exist_ok=True)
    return TestClient(create_decision_app(output_dir=data / "jczq", data_dir=data,
                                          launchctl=lambda: ""))


def _seed(data: Path) -> dict[str, str]:
    data.mkdir(parents=True, exist_ok=True)
    ids = {"k1": px.propose(data, title="K1 修正案", body="合并 κ", blocks="K1 判决",
                            at="2026-10-06T12:00:00+08:00"),
           "cr": px.propose(data, title="CR-cand-1", body="人群平局",
                            at="2026-10-07T12:00:00+08:00"),
           "old": px.propose(data, title="旧的", body="x", at="2026-10-01T12:00:00+08:00")}
    px.answer(data, ids["old"], "sign", words="可以", at="2026-10-02T09:00:00+08:00")
    return ids


def test_inbox_page_renders_with_nav_link_and_badge(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    page = _client(data).get("/inbox")
    assert page.status_code == 200
    assert "/static/decision/inbox.js" in page.text and "/static/decision/inbox.css" in page.text
    assert '<a href="/inbox" aria-current="page">待签' in page.text
    assert 'data-badge="inbox"' in page.text and ">2</span>" in page.text   # 两条待签


def test_nav_inbox_link_after_corrections_without_badge_when_empty(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    html = _client(data).get("/lab").text
    assert 'href="/inbox">待签</a>' in html and "nm-badge" not in html
    order = [html.index(f'href="/{p}"') for p in ("corrections", "inbox", "lab")]
    assert order == sorted(order)


def test_inbox_api_rows_summary_labels(tmp_path):
    data = tmp_path / "data"
    ids = _seed(data)
    body = _client(data).get("/api/inbox").json()
    assert body["errors"] == []
    assert [r["id"] for r in body["rows"]] == [ids["cr"], ids["k1"], ids["old"]]
    assert body["summary"]["pending"] == 2 and body["summary"]["overdue"] == 2
    assert body["labels"]["verdicts"] == {"sign": "签", "modify": "改", "reject": "否",
                                          "stale": "已过时"}
    assert body["labels"]["statuses"]["pending"] == "待签"
    k1 = body["rows"][1]
    assert k1["blocks"] == "K1 判决" and k1["overdue"] is True and k1["asked_count"] == 1


def test_inbox_api_bad_ledger_does_not_500(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / px.LEDGER).write_text("不是 json\n", encoding="utf-8")
    body = _client(data).get("/api/inbox").json()
    assert body["rows"] == [] and body["summary"]["pending"] == 0


def test_answer_post_success_400_404(tmp_path):
    data = tmp_path / "data"
    ids = _seed(data)
    c = _client(data)
    r = c.post(f"/action/inbox/{ids['k1']}/answer", json={"verdict": "sign", "words": "签了"})
    assert r.status_code == 200 and r.json()["ok"]
    (row,) = [x for x in px.load(data) if x["id"] == ids["k1"]]
    assert (row["status"], row["words"], row["by"]) == ("sign", "签了", "jun")
    assert c.post(f"/action/inbox/{ids['cr']}/answer",
                  json={"verdict": "modify", "words": ""}).status_code == 400
    assert c.post(f"/action/inbox/{ids['cr']}/answer", json={"verdict": "ok"}).status_code == 400
    assert c.post("/action/inbox/P-deadbeef/answer", json={"verdict": "sign"}).status_code == 404
    r = c.post(f"/action/inbox/{ids['cr']}/answer", json={"verdict": "modify", "words": "只记"})
    assert r.status_code == 200
    assert c.get("/api/inbox").json()["summary"]["pending"] == 0
    assert "nm-badge" not in c.get("/inbox").text


def test_open_rsi_item_is_listed_and_answerable(tmp_path):
    data = tmp_path / "data"
    d = data / px.RSI_DIR
    d.mkdir(parents=True)
    (d / "inbox.json").write_text(json.dumps({"rubric_cap:F_x": {
        "id": "RSI-abc123", "first_seen": "2026-10-29", "last_seen": "2026-10-29"}}),
        encoding="utf-8")
    (d / "2026-10-29.json").write_text(json.dumps({"inbox": [
        {"key": "rubric_cap:F_x", "id": "RSI-abc123", "text": "rubric F_x 上限",
         "default": "改上限", "command": ""}]}, ensure_ascii=False), encoding="utf-8")
    c = _client(data)
    (row,) = c.get("/api/inbox").json()["rows"]
    rid = "RSI-abc123@2026-10-29"
    assert (row["id"], row["source"], row["body"]) == (rid, "rsi", "默认：改上限")
    assert 'data-badge="inbox"' in c.get("/inbox").text
    assert c.post(f"/action/inbox/{rid}/answer", json={"verdict": "stale"}).status_code == 200
    (row,) = c.get("/api/inbox").json()["rows"]
    assert row["status"] == "stale"


def test_inbox_static_assets_served(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    c = _client(data)
    assert c.get("/static/decision/inbox.js").status_code == 200
    assert c.get("/static/decision/inbox.css").status_code == 200
