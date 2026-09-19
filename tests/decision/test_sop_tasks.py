from pathlib import Path

from nutmeg.decision.sop_tasks import STEPS, SopParams, run_step, step_by_id
from nutmeg.decision.workbench import read_events


def test_registry_has_the_deterministic_lane_b_steps_in_runbook_order():
    assert [s.step_id for s in STEPS] == [
        "B0_prep_morning", "B1_prep_afternoon", "B2_canonical", "B3a_premise_card",
        "B4_build_reads", "B4b_candidates", "B5c_plan_tiers", "B5_plan_frontier",
        "B6_audit", "B6b_adjudicate_issue", "B9_plan_commit",
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


class _FakeInvoker:
    """替身：不真跑 CLI，只记录 argv 并返回预设退出码/输出。"""

    def __init__(self, exit_code=0, output="ok\nline2\n"):
        self.exit_code, self.output, self.calls = exit_code, output, []

    def __call__(self, argv):
        self.calls.append(argv)
        return self.exit_code, self.output


def test_run_step_writes_started_and_done_events_with_output_tail(tmp_path):
    p = SopParams(issue="26129", date="2026-09-19", zucai_dir=tmp_path / "z",
                  output_dir=tmp_path / "o", legs_file=None)
    inv = _FakeInvoker()
    result = run_step("B0_prep_morning", p, invoke=inv)
    assert inv.calls == [["zucai-prep", "--slot", "morning", "--issue", "26129"]]
    assert result["ok"] is True and result["exit_code"] == 0
    evs = read_events(tmp_path / "o", "2026-09-19")
    assert [e["kind"] for e in evs] == ["task_started", "task_done"]
    assert evs[1]["obj_id"] == "task:B0_prep_morning" and "line2" in evs[1]["text"]


def test_audit_exit_1_is_done_not_failed(tmp_path):
    p = SopParams(issue="26129", date="2026-09-19", zucai_dir=tmp_path / "z",
                  output_dir=tmp_path / "o", legs_file=tmp_path / "legs.json")
    result = run_step("B6_audit", p, invoke=_FakeInvoker(exit_code=1, output="1 个 ERROR"))
    assert result["ok"] is True                       # 判决≠崩溃
    assert read_events(tmp_path / "o", "2026-09-19")[-1]["kind"] == "task_done"


def test_unexpected_exit_code_is_task_failed(tmp_path):
    p = SopParams(issue="26129", date="2026-09-19", zucai_dir=tmp_path / "z",
                  output_dir=tmp_path / "o", legs_file=None)
    result = run_step("B0_prep_morning", p, invoke=_FakeInvoker(exit_code=2, output="boom"))
    assert result["ok"] is False
    assert read_events(tmp_path / "o", "2026-09-19")[-1]["kind"] == "task_failed"


def test_step_needing_legs_refuses_without_legs_file(tmp_path):
    p = SopParams(issue="26129", date="2026-09-19", zucai_dir=tmp_path / "z",
                  output_dir=tmp_path / "o", legs_file=None)
    inv = _FakeInvoker()
    result = run_step("B6_audit", p, invoke=inv)
    assert result["ok"] is False and inv.calls == [] and "legs_file" in result["error"]


def test_plan_steps_are_registered_in_lane_order():
    ids = [step.step_id for step in STEPS]
    assert ids.index("B5c_plan_tiers") < ids.index("B5_plan_frontier") < ids.index("B6_audit")
    assert ids.index("B9_plan_commit") > ids.index("B6b_adjudicate_issue")
    params = SopParams(
        issue="26130", date="2026-09-26", zucai_dir=Path("z"), output_dir=Path("o")
    )
    assert step_by_id("B5c_plan_tiers").argv(params) == [
        "plan",
        "tiers",
        "--issue",
        "26130",
        "--data-dir",
        "o/..",
    ]
    assert step_by_id("B5_plan_frontier").argv(params)[:4] == [
        "plan",
        "frontier",
        "--issue",
        "26130",
    ]
    assert step_by_id("B9_plan_commit").argv(params)[:6] == [
        "plan",
        "commit",
        "--issue",
        "26130",
        "--cap-source",
        "baseline",
    ]
