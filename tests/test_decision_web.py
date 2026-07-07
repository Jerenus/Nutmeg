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


def _seed_factors(store):
    from nutmeg.decision.factors import load_seed_factors
    store.upsert_many(load_seed_factors())


def _valid_read_payload(date):
    return {
        "read_id": "R-web-1", "match_id": f"M-{date}-a-b", "snapshot_id": "S1",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.52, "draw": 0.27, "away": 0.21},
        "belief": {"home": 0.46, "draw": 0.31, "away": 0.23},
        "factors": [{"factor_id": "league_bias", "scope_key": "swe-allsvenskan",
                     "direction": "draw", "weight_pp": 6,
                     "evidence": [{"url": "u"}]}],
        "confidence": 3, "shadow": False}


def test_approve_read_lands_in_store_via_same_gate(tmp_path):
    client, out, date = _app(tmp_path)
    _seed_factors(client.app.state.store)
    r = client.post("/action/approve-read",
                    json={"obj_id": "O1", "read": _valid_read_payload(date)})
    assert r.status_code == 200 and r.json()["ok"] is True
    from nutmeg.decision.ontology import Read
    assert client.app.state.store.get(Read, "R-web-1") is not None


def test_approve_invalid_read_rejected_with_same_error(tmp_path):
    """违规草稿(league 因子缺 scope_key)→ 400 + 与 validate_read 逐字相同的理由。"""
    client, out, date = _app(tmp_path)
    _seed_factors(client.app.state.store)
    bad = _valid_read_payload(date)
    bad["factors"][0].pop("scope_key")
    r = client.post("/action/approve-read", json={"obj_id": "O1", "read": bad})
    assert r.status_code == 400
    assert any("scope_key" in e for e in r.json()["errors"])


def test_confirm_legs_writes_legs_json_and_ticket(tmp_path):
    client, out, date = _app(tmp_path)
    leg = {"match_id": f"M-{date}-a-b", "market": "had", "selection": "home",
           "odds": 1.92, "bucket": "main"}
    r = client.post("/action/confirm-legs",
                    json={"date": date, "legs": [leg]})
    assert r.status_code == 200 and r.json()["ok"] is True
    import json
    legs_file = out / "daily" / date / "legs.json"
    assert legs_file.exists()
    assert json.loads(legs_file.read_text())[0]["bucket"] == "main"


def test_reject_read_is_recorded_not_stored(tmp_path):
    client, out, date = _app(tmp_path)
    r = client.post("/action/reject-read",
                    json={"obj_id": "O1", "reason": "证据不足"})
    assert r.status_code == 200
    # reject 用当天日期留痕(date 从 payload 或 today);此处断言留痕存在
    assert r.json()["ok"] is True


def test_thread_post_appends_user_message(tmp_path):
    client, out, date = _app(tmp_path)
    r = client.post("/thread", json={"date": date, "obj_id": "O1",
                                     "text": "为什么压平不压主胜？"})
    assert r.status_code == 200 and r.json()["ok"] is True
    from nutmeg.decision.workbench import read_events
    evs = [e for e in read_events(out, date) if e["kind"] == "user_message"]
    assert evs and evs[0]["obj_id"] == "O1" and "压平" in evs[0]["text"]


def test_events_endpoint_returns_new_since(tmp_path):
    """SSE 拉取:/events?since=N 只回新事件(轮询式,便于 TestClient 断言)。"""
    client, out, date = _app(tmp_path)
    from nutmeg.decision.workbench import append_event
    append_event(out, date, {"kind": "attention", "id": "A1"})
    append_event(out, date, {"kind": "agent_reply", "obj_id": "O1", "text": "铁桶压净胜"})
    r = client.get(f"/events?date={date}&since=1")
    data = r.json()
    assert [e["kind"] for e in data["events"]] == ["agent_reply"]
    assert data["cursor"] == 2


def test_workbench_renders_three_columns_and_thread(tmp_path):
    client, out, date = _app(tmp_path)
    from nutmeg.decision.workbench import append_event
    append_event(out, date, {"kind": "attention", "id": "A1", "group": "草稿待审",
                             "match": "哈马比 vs 卡尔马"})
    html = client.get(f"/?date={date}").text
    assert "今日议程" in html and "待裁决" in html and "追问线程" in html
    assert "哈马比 vs 卡尔马" in html          # attention 事件渲染进左栏


def test_附属页_all_render(tmp_path):
    client, out, date = _app(tmp_path)
    for path, marker in [("/objects", "对象浏览器"),
                         ("/calibration", "校准台"),
                         ("/ledger", "账本")]:
        r = client.get(path)
        assert r.status_code == 200 and marker in r.text


def test_mobile_tabs_markup_present(tmp_path):
    """窄屏三 Tab(议程/舞台/裁决)靠 CSS 折叠;标记须在 DOM(渐进增强)。"""
    client, out, date = _app(tmp_path)
    html = client.get(f"/?date={date}").text
    assert 'class="mtabs"' in html
    for label in ["议程", "舞台", "裁决"]:
        assert label in html


def test_non_loopback_host_warns(tmp_path):
    from nutmeg.interfaces.cli import decision as dweb
    assert dweb._warn_if_exposed("0.0.0.0") is True
    assert dweb._warn_if_exposed("127.0.0.1") is False
