import json
import subprocess
from pathlib import Path

from nutmeg.decision.rsi_loop import (
    STEP_ORDER,
    LoopContext,
    planned_commands,
    run_loop,
)


def _fake_runner(log: list[list[str]]):
    def run(cmd):
        log.append(list(cmd))
        text = " ".join(cmd)
        if "rsi verdict" in text:
            return subprocess.CompletedProcess(
                cmd, 1, "", "rsi error: 未到期：n_cum=23，距 n_min 还差 97"
            )
        if "weights propose" in text:
            payload = {
                "factor_id": "draw_underpriced_band", "layer": "probability",
                "decision": "propose_zero", "reason": "n >= n_min but indistinguishable",
                "proposed_weight_pp": 0.0, "current_weight_pp": 0.0,
                "strict": {"n": 100, "verdict": "indistinguishable"},
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload) + "\n", "")
        if "rsi grade" in text:
            return subprocess.CompletedProcess(cmd, 0, "F3 [prospective] n=23  残差 +8.63pp\n", "")
        if "team_strength" in text:
            return subprocess.CompletedProcess(cmd, 1, "", "Traceback: boom")
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    return run


def _ctx(tmp_path: Path, log, skip=()):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps({"rows": [{"src": "zucai", "issue": "26131"}]}), encoding="utf-8")
    return LoopContext(
        root=tmp_path, data_dir=tmp_path / "data", date="2026-09-22",
        runner=_fake_runner(log), corpus=corpus, skip=frozenset(skip),
    )


def test_planned_commands_cover_every_step(tmp_path):
    ctx = _ctx(tmp_path, [])
    plan = planned_commands(ctx)
    assert tuple(plan) == STEP_ORDER
    assert not {"hyp", "factor_search", "dream_compare"} & set(plan)   # 2026-10-04 删去
    assert all(c[:2] == ["uv", "run"] for name, step in plan.items() for c in step
               if name != "commit_outputs")        # 末尾的 git 提交步是 bash -c


def test_run_loop_classifies_not_due_failed_and_collects_human_actions(tmp_path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log, skip=("closing_backfill",))
    report = run_loop(ctx)
    assert report is not None
    by_name = {s.name: s for s in report.steps}
    assert by_name["closing_backfill"].status == "skipped"
    assert by_name["verdict_due"].status == "not_due"
    assert by_name["team_strength"].status == "failed"
    assert report.failed_steps == ["team_strength"]
    assert by_name["grade_prospective"].status == "ok"
    assert report.proposals[0]["decision"] == "propose_zero"
    assert report.quiet_factors == ["draw_underpriced_band"]   # 建议 0、现值 0：不进待人清单
    assert not any("draw_underpriced_band" in a for a in report.human_actions)
    assert any("团队" not in a and "步骤失败" in a for a in report.human_actions)
    out = ctx.out_dir
    assert (out / "2026-09-22.json").exists() and (out / "latest.md").exists()
    md = (out / "2026-09-22.md").read_text(encoding="utf-8")
    assert "待人决定" in md and "propose_zero" in md and "不需动作" in md
    assert "主指标（结构与决策）" in md and "次指标（程度判断）" in md
    assert "改权重、改规则、登记实验、部署全部由人执行" in md
    # never touched: no command edits factors.json / RULEBOOK / registry
    joined = "\n".join(" ".join(c) for c in log)
    assert "rsi deploy" not in joined and "rsi register" not in joined


def test_run_loop_is_idempotent_per_day_unless_forced(tmp_path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log)
    first = run_loop(ctx)
    calls_after_first = len(log)
    assert first is not None
    assert run_loop(ctx) is None and len(log) == calls_after_first
    assert run_loop(ctx, force=True) is not None and len(log) > calls_after_first


def test_commit_outputs_step_commits_only_the_loop_files_without_hooks(tmp_path):
    """Jun 2026-10-01：loop 末尾自动提交自己写的三个仓内文件；没变化静默、不跑 pre-commit。"""
    from nutmeg.decision.rsi_loop import LOOP_OUTPUT_PATHS, STEP_ORDER, planned_commands

    plan = planned_commands(_ctx(tmp_path, []))

    assert STEP_ORDER[-1] == "commit_outputs"
    [cmd] = plan["commit_outputs"]
    assert cmd[:2] == ["bash", "-c"]
    script = cmd[2]
    assert "git status --porcelain --" in script and "git commit --no-verify" in script
    assert all(path in script for path in LOOP_OUTPUT_PATHS)
    assert "experiments/corpus-v2.json" in LOOP_OUTPUT_PATHS
    assert "-- experiments/attempts.log" in script          # pathspec 提交，不碰别人暂存的


def test_loop_grades_registered_crowd_experiments(tmp_path):
    from nutmeg.decision.rsi_loop import graded_experiments

    reg = tmp_path / "experiments" / "registry"
    reg.mkdir(parents=True)
    (reg / "CR1.json").write_text("{}", encoding="utf-8")
    (reg / "_draft_H1.json").write_text("{}", encoding="utf-8")
    exps = graded_experiments(tmp_path)
    assert exps[-1] == "CR1" and "F14" in exps and "_draft_H1" not in exps


def test_unchanged_verdicts_are_carried_not_relisted(tmp_path: Path):
    """2026-10-12 降噪：同一判决日日重现「待人决定」；沿用的合并成一行并注明起始日。"""
    from nutmeg.decision.rsi_loop import StepResult, _collect, _verdict_streaks

    out = tmp_path / "rsi-loop"
    out.mkdir()
    line = "F9 → inconclusive（判据快照 {'bound': 'ci_upper'}）"
    for day in ("2026-09-19", "2026-09-20", "2026-09-21"):
        (out / f"{day}.json").write_text(
            json.dumps({"verdicts": [{"cmd": "x", "status": "ok", "line": line}]}),
            encoding="utf-8")
    (out / "2026-09-18.json").write_text(json.dumps({"verdicts": []}), encoding="utf-8")

    streaks = _verdict_streaks(out, "2026-09-22")
    assert streaks == {line: "2026-09-19"}

    step = StepResult("verdict_due", "ok", 1.0, "", {"commands": [
        {"cmd": "rsi verdict --exp F9", "status": "ok", "tail": line},
        {"cmd": "rsi verdict --exp K1", "status": "ok", "tail": "K1 → survived（判据快照 {}）"},
        {"cmd": "rsi verdict --exp F5", "status": "not_due", "tail": "未到期"},
    ]})
    _, _, verdicts, actions, _ = _collect([step], streaks=streaks)
    assert len(verdicts) == 3
    assert [a for a in actions if a.startswith("判决已出")] == [
        "判决已出：K1 → survived（判据快照 {}） → 若 survived 且 deploy_eligible，人决定 rsi deploy"
    ]
    assert any("判决沿用" in a and "F9 → inconclusive（自 2026-09-19）" in a for a in actions)
