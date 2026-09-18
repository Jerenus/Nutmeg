from pathlib import Path

from nutmeg.decision.sop_tasks import STEPS, SopParams, step_by_id


def test_registry_has_the_eight_deterministic_lane_b_steps_in_runbook_order():
    assert [s.step_id for s in STEPS] == [
        "B0_prep_morning", "B1_prep_afternoon", "B2_canonical", "B3a_premise_card",
        "B4_build_reads", "B4b_candidates", "B6_audit", "B6b_adjudicate_issue",
    ]


def test_argv_is_built_from_params_and_matches_the_runbook_command_lines():
    p = SopParams(issue="26129", date="2026-09-18", zucai_dir=Path(".nutmeg-data/zucai"),
                  output_dir=Path(".nutmeg-data/jczq"), legs_file=Path("x/legs.json"))
    assert step_by_id("B0_prep_morning").argv(p) == \
        ["zucai-prep", "--slot", "morning", "--issue", "26129"]
    assert step_by_id("B2_canonical").argv(p) == \
        ["decision-am", "--run-date", "2026-09-18", "--issue", "26129",
         "--output-dir", ".nutmeg-data/jczq"]
    assert step_by_id("B6_audit").argv(p) == ["decision-audit-legs", "--legs-file", "x/legs.json"]


def test_steps_declare_their_artifacts_so_the_ui_can_show_done_state():
    p = SopParams(issue="26129", date="2026-09-18", zucai_dir=Path("/z"),
                  output_dir=Path("/o"), legs_file=None)
    assert step_by_id("B0_prep_morning").artifacts(p) == [Path("/z/26129-prep-morning.json")]
    assert step_by_id("B4_build_reads").artifacts(p) == \
        [Path("/z/26129-reads.json"), Path("/z/26129-legs-base.json")]


def test_audit_step_treats_exit_code_1_as_a_verdict_not_a_crash():
    assert step_by_id("B6_audit").ok_exit_codes == (0, 1)
    assert step_by_id("B0_prep_morning").ok_exit_codes == (0,)
