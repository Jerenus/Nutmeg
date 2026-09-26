import json

from nutmeg.decision.kernel_submit import submit_unstarted

NOW = "2026-09-26T14:15:00+08:00"


def _read(mid, home=0.5):
    return {"read_id": f"R-{mid}", "match_id": mid, "judge": "ai-pool",
            "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "belief": {"home": home, "draw": 0.3, "away": 1 - 0.3 - home}}


def test_only_unstarted_and_changed_reads_are_submitted(tmp_path):
    state = tmp_path / "kernel-submitted.json"
    sent = []

    def submit(path):
        sent.append([r["match_id"] for r in json.loads(path.read_text(encoding="utf-8"))])
        return 0, "ok"

    kickoffs = {"started": "2026-09-26T14:00:00+08:00", "later": "2026-09-26T20:00:00+08:00"}
    first = submit_unstarted([_read("started"), _read("later")], kickoffs=kickoffs,
                             state_path=state, now=NOW, submit=submit)
    again = submit_unstarted([_read("later")], kickoffs=kickoffs,
                             state_path=state, now=NOW, submit=submit)
    changed = submit_unstarted([_read("later", home=0.52)], kickoffs=kickoffs,
                               state_path=state, now=NOW, submit=submit)

    assert (first, again, changed) == (["R-later"], [], ["R-later"])
    assert sent == [["later"], ["later"]]


def test_a_failed_submission_is_retried_next_time(tmp_path):
    state = tmp_path / "kernel-submitted.json"
    kickoffs = {"later": "2026-09-26T20:00:00+08:00"}

    failed = submit_unstarted([_read("later")], kickoffs=kickoffs, state_path=state,
                              now=NOW, submit=lambda path: (1, "boom"))
    retried = submit_unstarted([_read("later")], kickoffs=kickoffs, state_path=state,
                               now=NOW, submit=lambda path: (0, "ok"))

    assert (failed, retried) == ([], ["R-later"])
