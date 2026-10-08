# tests/test_decision_web.py
from fastapi.testclient import TestClient

from nutmeg.decision.workbench import append_event
from nutmeg.interfaces.decision_web import create_decision_app


def _kernel_state(date):
    """内核读侧替身：当天一场 + 一份 read_time 快照，无已提交 Read。"""
    return {
        "matches": [{"match_id": "match-1", "home": "哈马比", "away": "卡尔马",
                     "competition": "瑞超", "kickoff_at": date}],
        "snapshots": [{"snapshot_id": "S1", "match_id": "match-1", "kind": "read_time",
                       "fair": {"had": {"home": 0.52, "draw": 0.27, "away": 0.21}}}],
        "reads": [],
        "events": [],
    }


def _app(tmp_path, date="2026-07-08"):
    app = create_decision_app(output_dir=tmp_path, kernel_state=_kernel_state)
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


def test_retired_v1_routes_are_gone(tmp_path):
    """旧 DecisionStore 读写路由(批准/拒绝 Read、确认 legs、SOP 任务栏、对象/校准/账本页)已退役。"""
    client, out, date = _app(tmp_path)
    for path in ("/objects", "/calibration", "/ledger", "/api/sop-steps?issue=1&date=" + date):
        assert client.get(path).status_code == 404
    for path in ("/action/approve-read", "/action/reject-read", "/action/confirm-legs",
                 "/action/run-task"):
        assert client.post(path, json={}).status_code == 404


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
    append_event(out, date, {"kind": "attention", "id": "A1"})
    append_event(out, date, {"kind": "agent_reply", "obj_id": "O1", "text": "铁桶压净胜"})
    r = client.get(f"/events?date={date}&since=1")
    data = r.json()
    assert [e["kind"] for e in data["events"]] == ["agent_reply"]
    assert data["cursor"] == 2


def test_workbench_renders_three_columns_and_thread(tmp_path):
    client, out, date = _app(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1", "group": "草稿待审",
                             "match": "哈马比 vs 卡尔马"})
    html = client.get(f"/?date={date}").text
    assert "今日议程" in html and "待裁决" in html and "追问线程" in html
    assert "哈马比 vs 卡尔马" in html          # attention 事件渲染进左栏
    assert 'id="sopbar"' not in html


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
