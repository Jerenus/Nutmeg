from nutmeg.decision.workbench import append_candidate, append_note, read_events


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
