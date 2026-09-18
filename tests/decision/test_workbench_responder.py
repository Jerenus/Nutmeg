from nutmeg.decision.workbench import append_event
from nutmeg.decision.workbench_responder import pending_questions


def test_pending_questions_are_user_messages_without_a_later_agent_reply(tmp_path):
    d = "2026-09-19"
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-1", "text": "朗斯不败？"})
    append_event(tmp_path, d, {"kind": "agent_reply", "obj_id": "fr-1", "text": "…"})
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-1", "text": "那平呢？"})
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-2", "text": "拜仁稳吗？"})
    got = pending_questions(tmp_path, d)
    assert [(q["obj_id"], q["text"]) for q in got] == [("fr-1", "那平呢？"), ("fr-2", "拜仁稳吗？")]


def test_no_events_means_no_pending(tmp_path):
    assert pending_questions(tmp_path, "2026-09-19") == []
