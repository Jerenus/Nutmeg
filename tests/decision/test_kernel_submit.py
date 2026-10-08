from nutmeg.decision.kernel_submit import submit_unstarted
from nutmeg.decision.ontology_adapter import ReadSubmission

NOW = "2026-09-26T14:15:00+08:00"


def _read(mid, home=0.5):
    return {"read_id": f"R-{mid}", "match_id": mid, "judge": "ai-pool",
            "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "belief": {"home": home, "draw": 0.3, "away": 1 - 0.3 - home}}


def _receipt(reads, rejected=()):
    rejected = tuple(rejected)
    bad = {rid for rid, _why in rejected}
    return ReadSubmission(total=len(reads),
                          committed=tuple(r["read_id"] for r in reads if r["read_id"] not in bad),
                          rejected=rejected)


def test_only_unstarted_and_changed_reads_are_submitted(tmp_path):
    state = tmp_path / "kernel-submitted.json"
    sent = []

    def submit(reads):
        sent.append([r["match_id"] for r in reads])
        return _receipt(reads)

    kickoffs = {"started": "2026-09-26T14:00:00+08:00", "later": "2026-09-26T20:00:00+08:00"}
    first = submit_unstarted([_read("started"), _read("later")], kickoffs=kickoffs,
                             state_path=state, now=NOW, submit=submit)
    again = submit_unstarted([_read("later")], kickoffs=kickoffs,
                             state_path=state, now=NOW, submit=submit)
    changed = submit_unstarted([_read("later", home=0.52)], kickoffs=kickoffs,
                               state_path=state, now=NOW, submit=submit)

    assert (first, again, changed) == (["R-later"], [], ["R-later"])
    assert sent == [["later"], ["later"]]


def test_a_failed_submission_is_retried_next_time(tmp_path, capsys):
    state = tmp_path / "kernel-submitted.json"
    kickoffs = {"later": "2026-09-26T20:00:00+08:00"}

    def boom(_reads):
        raise RuntimeError("kernel offline")

    failed = submit_unstarted([_read("later")], kickoffs=kickoffs, state_path=state,
                              now=NOW, submit=boom)
    retried = submit_unstarted([_read("later")], kickoffs=kickoffs, state_path=state,
                               now=NOW, submit=_receipt)

    assert (failed, retried) == ([], ["R-later"])
    assert "kernel offline" in capsys.readouterr().err


def test_reads_rejected_inside_a_successful_batch_are_not_marked_submitted(tmp_path, capsys):
    # 整批交上去了，但内核拒了其中一条：它不能记成已交（26135 场11）；
    # 原因里带换行 / 分号也照样认得出（结构化回执，2026-10-08）
    state = tmp_path / "kernel-submitted.json"
    kickoffs = {"a": "2026-09-26T20:00:00+08:00", "b": "2026-09-26T21:00:00+08:00"}

    first = submit_unstarted(
        [_read("a"), _read("b")], kickoffs=kickoffs, state_path=state, now=NOW,
        submit=lambda reads: _receipt(reads, [("R-b", "does not sum to 1;\nsee: x")]))
    again = submit_unstarted([_read("a"), _read("b")], kickoffs=kickoffs, state_path=state,
                             now=NOW, submit=_receipt)

    assert (first, again) == (["R-a"], ["R-b"])
    assert "Read 交本体被拒 1 条" in capsys.readouterr().err
