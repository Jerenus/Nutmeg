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
    ctx = _ctx(tmp_path, log, skip=("team_strength",))   # 干净的一天（有失败步骤会重跑，见下）
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
    assert "experiments/corpus-v2.json" not in LOOP_OUTPUT_PATHS   # 2026-10-19 起不进 git
    assert "experiments/rsi-samples.json" in LOOP_OUTPUT_PATHS
    assert "-- experiments/attempts.log" in script          # pathspec 提交，不碰别人暂存的


def test_loop_grades_registered_crowd_experiments(tmp_path):
    from nutmeg.decision.rsi_loop import graded_experiments

    reg = tmp_path / "experiments" / "registry"
    reg.mkdir(parents=True)
    (reg / "CR1.json").write_text("{}", encoding="utf-8")
    (reg / "_draft_H1.json").write_text("{}", encoding="utf-8")
    exps = graded_experiments(tmp_path)
    assert exps[-1] == "CR1" and "F18" in exps and "_draft_H1" not in exps


def test_concluded_verdicts_are_classified_and_new_ones_listed_once(tmp_path: Path):
    """协议 v2（2026-10-19）：已结账的实验 `rsi verdict` 拒绝 → 记 concluded，不进待人清单；
    未到期的行带实验号；新判决只出现结账那一天。"""
    from nutmeg.decision.rsi_loop import _collect, _run_step

    def runner(cmd):
        exp = cmd[cmd.index("--exp") + 1]
        if exp == "F14":
            return subprocess.CompletedProcess(
                cmd, 1, "", "rsi error: 已结账（v2-frozen-text）：F14 → falsified @ 2026-10-19")
        if exp == "F10":
            return subprocess.CompletedProcess(
                cmd, 1, "", "rsi error: 未到期：n_cum=76，距 n_min 还差 74")
        return subprocess.CompletedProcess(cmd, 0, "F17 → survived（结算 n=120）\n", "")

    ctx = LoopContext(root=tmp_path, data_dir=tmp_path, date="2026-10-20", runner=runner)
    step = _run_step(ctx, "verdict_due", [
        ["uv", "run", "nutmeg", "rsi", "verdict", "--exp", e] for e in ("F14", "F10", "F17")])
    statuses = {c["cmd"].split()[-1]: c["status"] for c in step.detail["commands"]}
    assert statuses == {"F14": "concluded", "F10": "not_due", "F17": "ok"}
    tails = [c["tail"] for c in step.detail["commands"]]
    assert tails[1].startswith("F10: ")
    collected = _collect([step])
    assert len(collected.verdicts) == 3 and collected.inbox == []
    assert collected.notes == ["判决已出（观察型，作为正样本）：F17 → survived（结算 n=120）"]


def test_every_registered_experiment_is_graded_or_explained():
    """2026-10-19：F18 有适配器却不在清单（10-15 开窗后 n=0）、F10/F11 漏结账三天——
    每个登记原件必须落在 结账 / 不结账（有原因）/ 已关闭 三处之一，结账的必须有适配器。"""
    from nutmeg.decision.rsi_grading import PROSPECTIVE_ADAPTERS
    from nutmeg.decision.rsi_loop import CLOSED, GRADED_EXPERIMENTS, MONITORS, UNGRADED

    root = Path(__file__).resolve().parents[2]
    registered = {p.stem for p in (root / "experiments" / "registry").glob("*.json")
                  if not p.stem.startswith("_")}
    crowd = {e for e in registered if e.startswith("CR")}
    placed = set(GRADED_EXPERIMENTS) | set(UNGRADED) | set(CLOSED) | crowd
    assert registered - placed == set(), f"未落位的登记实验：{sorted(registered - placed)}"
    assert not set(GRADED_EXPERIMENTS) & (set(UNGRADED) | set(CLOSED))
    assert set(GRADED_EXPERIMENTS) <= set(PROSPECTIVE_ADAPTERS)
    assert set(MONITORS) <= set(GRADED_EXPERIMENTS)


def _registry(root: Path, exp: str, exits: dict | None) -> None:
    reg = root / "experiments" / "registry"
    reg.mkdir(parents=True, exist_ok=True)
    doc = {"exp_id": exp, **({"exits": exits} if exits else {})}
    (reg / f"{exp}.json").write_text(json.dumps(doc), encoding="utf-8")


def test_new_verdicts_route_to_their_registered_exit():
    """2026-10-19 Jun 裁 4：展示类出口自动生效只记一笔；改规则/码表的出口进收件箱；
    没写出口的＝观察型，作为正样本记一笔。"""
    import tempfile

    from nutmeg.decision.rsi_loop import StepResult, _collect

    root = Path(tempfile.mkdtemp())
    _registry(root, "F18", {"on_survived": "packet_column:许可证",
                            "on_falsified": "retire_rule:licence-dan-gate", "on_expired": "none"})
    _registry(root, "F10", {"on_survived": "packet_column:热门带", "on_falsified": "display_only",
                            "on_expired": "none"})
    _registry(root, "F99", None)
    step = StepResult("verdict_due", "ok", 1.0, "", {"commands": [
        {"cmd": "rsi verdict --exp F18", "status": "ok", "tail": "F18 → falsified（结算 n=60）"},
        {"cmd": "rsi verdict --exp F10", "status": "ok", "tail": "F10 → survived（结算 n=150）"},
        {"cmd": "rsi verdict --exp F99", "status": "ok", "tail": "F99 → survived（结算 n=40）"},
    ]})
    collected = _collect([step], root=root)
    inbox = collected.inbox
    assert [i["key"] for i in inbox] == ["exit:F18:falsified"]
    assert "retire_rule:licence-dan-gate" in inbox[0]["text"]
    assert any("F10" in n and "packet_column:热门带" in n and "自动" in n for n in collected.notes)
    assert any("F99" in n and "观察型" in n for n in collected.notes)


def test_rubric_proposals_map_to_the_live_caps_and_upward_moves_are_not_executable(monkeypatch):
    import functools

    from nutmeg.decision import rubric_items
    from nutmeg.decision.rsi_loop import StepResult, _collect

    rows = [
        {"factor_id": "rubric_F_suspension", "layer": "probability", "decision": "propose_zero",
         "proposed_weight_pp": 0.0, "current_weight_pp": 0.0, "strict": {"n": 140}},
        {"factor_id": "rubric_F_absence_home", "layer": "probability",
         "decision": "propose_zero", "proposed_weight_pp": 0.0, "current_weight_pp": 0.0,
         "strict": {"n": 160}},                                   # r2 上限已是 0：不需动作
        {"factor_id": "belief_offset_anchor", "layer": "probability",
         "decision": "propose_change", "proposed_weight_pp": 15.0, "current_weight_pp": 0.0,
         "strict": {"n": 223}},                                   # 非 rubric 因子：权重无执行开关
    ]
    step = StepResult("factor_propose", "ok", 1.0, "", {"commands": [
        {"cmd": "rsi weights propose --all", "status": "ok", "tail": "",
         "json": rows}]})
    # r3（2026-10-20）起 F_suspension 上限已是 0：同一提案不再进收件箱
    live = _collect([step])
    assert live.inbox == [] and "rubric_F_suspension" in live.quiet
    # 按 r2 的上限读（F_suspension 4pp）：映射到真上限、进收件箱
    monkeypatch.setattr(rubric_items, "cap_at",
                        functools.partial(rubric_items.cap_at, version="r2"))
    collected = _collect([step])
    assert [i["key"] for i in collected.inbox] == ["rubric_cap:F_suspension"]
    assert "4pp → 0" in collected.inbox[0]["text"]
    assert "rubric_F_absence_home" in collected.quiet
    assert any("belief_offset_anchor" in n and "无执行开关" in n for n in collected.notes)


def test_inbox_ids_are_stable_and_ages_accumulate_until_the_item_goes_away(tmp_path):
    from nutmeg.decision.rsi_loop import update_inbox

    item = {"key": "rubric_cap:F_suspension", "text": "t", "default": "d", "command": ""}
    first = update_inbox(tmp_path, "2026-10-20", [item])
    later = update_inbox(tmp_path, "2026-10-27", [item])
    assert first[0]["id"] == later[0]["id"] and later[0]["age_days"] == 7
    assert later[0]["first_seen"] == "2026-10-20"
    assert update_inbox(tmp_path, "2026-10-28", []) == []
    state = json.loads((tmp_path / "inbox.json").read_text(encoding="utf-8"))
    assert state["rubric_cap:F_suspension"]["closed_at"] == "2026-10-28"
    again = update_inbox(tmp_path, "2026-11-01", [item])           # 再出现＝重新起算
    assert again[0]["first_seen"] == "2026-11-01" and again[0]["id"] == first[0]["id"]


def test_a_failed_corpus_build_skips_the_steps_that_would_read_a_stale_corpus(tmp_path):
    """2026-10-19：语料重建失败后照样拿旧语料结账、判决。依赖它的步改记 skipped；
    当天报告有失败步骤时，再触发会重跑（不再被「同日已有报告」挡住）。"""
    calls: list[str] = []

    def runner(cmd):
        text = " ".join(cmd)
        calls.append(text)
        if "corpus_build.py" in text:
            return subprocess.CompletedProcess(cmd, 1, "", "Traceback: boom")
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    ctx = LoopContext(root=tmp_path, data_dir=tmp_path / "data", date="2026-10-20",
                      runner=runner)
    report = run_loop(ctx)
    by_name = {s.name: s for s in report.steps}
    for name in ("grade_prospective", "verdict_due", "factor_propose"):
        assert by_name[name].status == "skipped" and "corpus_build" in by_name[name].summary
    assert not any("rsi grade" in c or "rsi verdict" in c for c in calls)
    assert report.failed_steps == ["corpus_build"]
    assert run_loop(ctx) is not None                       # 有失败步骤：再触发就重跑
