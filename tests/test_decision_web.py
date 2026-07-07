# tests/test_decision_web.py
from fastapi.testclient import TestClient

from nutmeg.decision.ontology import MarketSnapshot, Match
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.workbench import append_event
from nutmeg.interfaces.decision_web import create_decision_app


def _app(tmp_path, date="2026-07-08"):
    store = DecisionStore(tmp_path / "decision")
    store.upsert(Match(match_id=f"M-{date}-a-b", kickoff_at="t", home="哈马比",
                       away="卡尔马", competition="瑞超"))
    store.upsert(MarketSnapshot(snapshot_id="S1", match_id=f"M-{date}-a-b",
                                taken_at="t", kind="read_time", source="apifootball",
                                fair={"had": {"home": 0.52, "draw": 0.27, "away": 0.21}}))
    app = create_decision_app(store=store, output_dir=tmp_path)
    return TestClient(app), tmp_path, date


def test_workbench_api_returns_day_state(tmp_path):
    client, out, date = _app(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1", "group": "草稿待审",
                             "match": "哈马比 vs 卡尔马"})
    r = client.get(f"/api/workbench?date={date}")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == date
    assert any(m["home"] == "哈马比" for m in body["matches"])
    assert any(e["kind"] == "attention" for e in body["events"])


def test_workbench_page_renders(tmp_path):
    client, out, date = _app(tmp_path)
    r = client.get(f"/?date={date}")
    assert r.status_code == 200
    assert "判读工作台" in r.text


def test_empty_day_is_explicit_not_silent(tmp_path):
    client, out, date = _app(tmp_path, date="2026-07-09")
    r = client.get("/api/workbench?date=2026-07-09")
    assert r.status_code == 200
    assert r.json()["events"] == []   # 无 workbench.jsonl → 空事件,不报错
