from nutmeg.decision.workbench import (
    append_candidate,
    append_event,
    append_note,
    read_events,
)
from nutmeg.decision.workbench_export import events_to_markdown


def test_note_and_candidate_events_have_stable_shapes(tmp_path):
    d = "2026-09-19"
    append_note(tmp_path, d, obj_id="ticket:26129", text="SFC-B 否决：C2 ×3（旗面没盖住）")
    append_candidate(tmp_path, d, obj_id="ticket:26129", version="SFC-B",
                     faces={"1": "30", "2": "3"}, notes=128, stake_yuan=256,
                     p_all=0.0038, verdict="rejected", reason="三处 C2")
    n, c = read_events(tmp_path, d)
    assert n["kind"] == "note" and n["obj_id"] == "ticket:26129" and "C2" in n["text"]
    assert c["kind"] == "candidate" and c["payload"]["version"] == "SFC-B"
    assert c["payload"]["verdict"] == "rejected" and c["payload"]["stake_yuan"] == 256


def test_markdown_export_is_a_retro_skeleton(tmp_path):
    d = "2026-09-19"
    append_event(tmp_path, d, {"kind": "task_done", "obj_id": "task:B6_audit",
                               "label": "B6 审计门", "exit_code": 1, "text": "1 个 ERROR"})
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-8", "text": "朗斯不败？"})
    append_event(tmp_path, d, {"kind": "agent_reply", "obj_id": "fr-8", "text": "平局最被支持。"})
    append_candidate(tmp_path, d, obj_id="ticket:26129", version="SFC-D", faces={}, notes=192,
                     stake_yuan=384, p_all=0.00321, verdict="chosen", reason="裸单全 ≥50%")
    md = events_to_markdown(tmp_path, d)
    assert md.startswith("# 2026-09-19 过程回放")
    assert "## 任务" in md and "B6 审计门 · exit=1" in md
    assert "## 追问" in md and "**你**（fr-8）：朗斯不败？" in md and "**判**：平局最被支持。" in md
    assert "## 候选票面" in md and "SFC-D · 已选 · 192 注 ¥384 · P 0.32%" in md
