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


def test_reads_rejected_inside_a_successful_batch_are_not_marked_submitted(tmp_path, capsys):
    # decision-read 整批退出码 0，但输出里列了被拒的那条：它不能记成已交（26135 场11）
    state = tmp_path / "kernel-submitted.json"
    kickoffs = {"a": "2026-09-26T20:00:00+08:00", "b": "2026-09-26T21:00:00+08:00"}
    out = ("decision-read-v2: 摄取 1/2 条 Read(kernel) | 拒绝: "
           "R-b:distribution does not sum to 1")

    first = submit_unstarted([_read("a"), _read("b")], kickoffs=kickoffs, state_path=state,
                             now=NOW, submit=lambda path: (0, out))
    again = submit_unstarted([_read("a"), _read("b")], kickoffs=kickoffs, state_path=state,
                             now=NOW, submit=lambda path: (0, "ok"))

    assert (first, again) == (["R-a"], ["R-b"])
    assert "Read 交本体被拒 1 条" in capsys.readouterr().err


def test_rejected_read_ids_parses_the_decision_read_summary():
    from nutmeg.decision.kernel_submit import rejected_read_ids

    assert rejected_read_ids("decision-read-v2: 摄取 2/2 条 Read(kernel)") == set()
    assert rejected_read_ids("x | 旧式因子丢弃 1 | 拒绝: R-1:unresolved_match; R-2:boom") == {
        "R-1", "R-2"}
