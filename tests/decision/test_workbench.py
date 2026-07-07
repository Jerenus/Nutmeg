# tests/decision/test_workbench.py
from nutmeg.decision.workbench import (
    append_event,
    append_user_message,
    distill_note,
    read_events,
    record_decision,
)


def _daily(tmp_path, date="2026-07-08"):
    d = tmp_path / "daily" / date
    d.mkdir(parents=True)
    return tmp_path, date


def test_append_and_read_events_roundtrip(tmp_path):
    out, date = _daily(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1", "match": "哈马比 vs 卡尔马"})
    append_event(out, date, {"kind": "read_draft", "id": "D1", "obj_id": "O1",
                             "payload": {"belief": {"home": 0.46}}})
    events = read_events(out, date)
    assert [e["kind"] for e in events] == ["attention", "read_draft"]
    assert events[1]["payload"]["belief"]["home"] == 0.46


def test_read_events_after_offset_for_sse(tmp_path):
    """SSE tail:只取序号 > since 的新事件(每事件带自增 seq)。"""
    out, date = _daily(tmp_path)
    append_event(out, date, {"kind": "attention", "id": "A1"})
    append_event(out, date, {"kind": "attention", "id": "A2"})
    tail = read_events(out, date, since=1)
    assert [e["id"] for e in tail] == ["A2"]
    assert tail[0]["seq"] == 2


def test_append_user_message_is_an_event(tmp_path):
    """§3.5:浏览器追问写进同一事件流,obj_id 锚定。"""
    out, date = _daily(tmp_path)
    append_user_message(out, date, obj_id="O1", text="为什么压平不压主胜？")
    ev = read_events(out, date)[0]
    assert ev["kind"] == "user_message"
    assert ev["obj_id"] == "O1" and "压平" in ev["text"]


def test_record_decision_appends_to_decisions_log(tmp_path):
    out, date = _daily(tmp_path)
    record_decision(out, date, action="approve_read", obj_id="O1", result="R-1 入库")
    import json
    line = (out / "daily" / date / "decisions.jsonl").read_text().strip()
    rec = json.loads(line)
    assert rec["action"] == "approve_read" and rec["obj_id"] == "O1"


def test_distill_note_summarizes_thread(tmp_path):
    """收敛蒸馏:把某 obj 的 user/agent 往来压成一句进 Read.note(不进 store)。"""
    out, date = _daily(tmp_path)
    append_user_message(out, date, obj_id="O1", text="战意呢？")
    append_event(out, date, {"kind": "agent_reply", "obj_id": "O1", "text": "争四动力足"})
    note = distill_note(out, date, obj_id="O1")
    assert "战意" in note and "争四" in note
