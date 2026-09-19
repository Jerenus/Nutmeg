"""接线只加一行：备料链跑完 → rsi schedule + due；观察仪落盘 → rsi fulfill；
结算跑完 → rsi grade (+verdict)。用假 invoker 验参数。"""
from datetime import datetime

from nutmeg.decision.rsi_wiring import (
    after_am,
    after_observation_artifact,
    after_prep,
    after_settle,
)


def test_after_prep_schedules_then_lists_due(tmp_path):
    calls = []
    after_prep(issue="26129", day="2026-09-19", data_dir=tmp_path,
               invoke=lambda argv: calls.append(argv) or (0, ""))
    assert calls[0][:2] == ["rsi", "schedule"] and "--issue" in calls[0] and "26129" in calls[0]
    assert calls[1][:2] == ["rsi", "due"]


def test_after_am_builds_research_board_then_schedules_match_duties(tmp_path):
    calls = []
    after_am(day="2026-09-19", data_dir=tmp_path,
             invoke=lambda argv: calls.append(argv) or (0, ""))
    assert [call[:2] for call in calls] == [["research", "board"], ["rsi", "schedule"]]


def test_decision_am_calls_research_wiring_after_success(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import nutmeg.config.settings as settings_module
    import nutmeg.interfaces.cli as cli
    from nutmeg.decision.verbs import DecisionWorkflowResult

    monkeypatch.delenv("NUTMEG_ONTOLOGY_V2", raising=False)
    settings_module.get_settings.cache_clear()
    monkeypatch.setattr(
        "nutmeg.decision.verbs.run_decision_am",
        lambda run_date, output_dir, **kwargs: DecisionWorkflowResult(
            "decision-am", run_date, (), "stub"
        ),
    )
    hits = []
    monkeypatch.setattr(
        "nutmeg.decision.rsi_wiring.after_am", lambda **kwargs: hits.append(kwargs)
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "decision-am",
            "--run-date",
            "2026-09-19",
            "--output-dir",
            str(tmp_path / "jczq"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert hits == [{"day": "2026-09-19", "data_dir": tmp_path}]


def test_after_observation_artifact_fulfills_with_row_count(tmp_path):
    calls = []
    art = tmp_path / "26129-f2-observation.json"
    art.write_text('{"observations": {"1": {}, "2": {}}}')
    after_observation_artifact(exp="F2", duty="f2-observation", issue="26129", day="2026-09-19",
                               artifact=art, n_rows=2, data_dir=tmp_path,
                               invoke=lambda argv: calls.append(argv) or (0, ""))
    assert calls[0][:2] == ["rsi", "fulfill"] and "--n-rows" in calls[0] and "2" in calls[0]


def test_after_capital_plan_fulfills_f4_with_the_plan_hash(tmp_path):
    from nutmeg.decision.rsi_wiring import after_capital_plan

    calls = []
    after_capital_plan(
        exp="F4",
        issue="26130",
        day="2026-09-26",
        plan_id="zcp-abc",
        data_dir=tmp_path,
        captured_at=datetime.fromisoformat("2026-09-25T20:00:00+08:00"),
        invoke=lambda argv: calls.append(argv) or (0, ""),
    )
    assert calls[0][:4] == ["rsi", "fulfill", "--exp", "F4"]
    assert "--artifact" in calls[0]
    artifact = tmp_path / "zucai" / "26130-capital-plan.txt"
    assert int(artifact.stat().st_mtime) == int(
        datetime.fromisoformat("2026-09-25T20:00:00+08:00").timestamp()
    )


def test_cli_invoke_never_raises_on_failure(tmp_path, capsys):
    """登记失败只打印警告并返回非零——绝不能让备料链/观察仪的主任务跟着失败。"""
    from nutmeg.decision.rsi_wiring import _cli_invoke

    # 不存在的 issue.json → `rsi schedule` 以退出码 1 结束；接线层必须吞掉而非抛出。
    rc, out = _cli_invoke(["rsi", "schedule", "--day", "2026-09-19", "--issue", "99999",
                           "--data-dir", str(tmp_path / "data")])
    assert rc != 0
    assert isinstance(out, str)
    assert "rsi 接线未成功" in capsys.readouterr().out


# ---- 结算后：grade → verdict（spec §8.1 第 3 项）----

def _fake_invoke(calls, replies):
    """按 argv[1]（grade/verdict）回放 (exit_code, output)。"""
    def invoke(argv):
        calls.append(argv)
        return replies[argv[1]]
    return invoke


def test_after_settle_grades_then_verdicts_each_observing_experiment(tmp_path):
    calls = []
    report = after_settle(
        day="2026-09-19", data_dir=tmp_path, experiments=["F2"],
        invoke=_fake_invoke(calls, {
            "grade": (0, "F2 [prospective] n=10"),
            "verdict": (1, "rsi error: 未到期：n_cum=10，距 n_min 还差 130"),
        }))
    assert report == {"F2": "not_due"}
    assert [c[:2] for c in calls] == [["rsi", "grade"], ["rsi", "verdict"]]
    grade = calls[0]
    assert "--exp" in grade and "F2" in grade
    assert grade[grade.index("--mode") + 1] == "prospective"
    assert grade[grade.index("--data-dir") + 1] == str(tmp_path)
    verdict = calls[1]
    assert verdict[verdict.index("--exp") + 1] == "F2"
    assert verdict[verdict.index("--data-dir") + 1] == str(tmp_path)


def test_after_settle_skips_experiments_without_an_adapter(tmp_path):
    calls = []
    report = after_settle(
        day="2026-09-19", data_dir=tmp_path, experiments=["F5"],
        invoke=_fake_invoke(calls, {
            "grade": (1, "rsi error: F5 的结账适配器尚未接入（replay_spec.harness=...）"),
            "verdict": (0, "should never be called"),
        }))
    assert report == {"F5": "skipped_no_adapter"}
    assert [c[:2] for c in calls] == [["rsi", "grade"]]


def test_after_settle_records_a_verdict_when_due(tmp_path):
    calls = []
    report = after_settle(
        day="2026-09-19", data_dir=tmp_path, experiments=["F2"],
        invoke=_fake_invoke(calls, {
            "grade": (0, "F2 [prospective] n=140"),
            "verdict": (0, "F2 → falsified（判据快照 ...）"),
        }))
    assert report == {"F2": "verdict_recorded"}
    assert [c[:2] for c in calls] == [["rsi", "grade"], ["rsi", "verdict"]]


def test_after_settle_never_raises_into_caller(tmp_path, capsys):
    """结算主任务不能因 RSI 结账失败而失败：invoke 抛异常也只登记 error 并继续。"""
    def boom(argv):
        raise RuntimeError("kernel exploded")

    report = after_settle(day="2026-09-19", data_dir=tmp_path, experiments=["F2", "F4"],
                          invoke=boom)
    assert set(report) == {"F2", "F4"}
    assert all(v == "error" for v in report.values())
    assert "rsi" in capsys.readouterr().out


# ---- decision-settle 的挂钩：只有 --no-dry-run 才碰 RSI ----

def _spy_after_settle(monkeypatch):
    hits = []
    monkeypatch.setattr("nutmeg.decision.rsi_wiring.after_settle",
                        lambda **kw: hits.append(kw) or {})
    return hits


def _stub_settle(monkeypatch):
    import nutmeg.config.settings as settings_module
    from nutmeg.decision.verbs import DecisionWorkflowResult

    monkeypatch.delenv("NUTMEG_ONTOLOGY_V2", raising=False)
    settings_module.get_settings.cache_clear()
    monkeypatch.setattr(
        "nutmeg.decision.verbs.run_decision_settle",
        lambda rd, od, **k: DecisionWorkflowResult("decision-settle", rd, (), "stub"))


def test_decision_settle_dry_run_does_not_touch_rsi(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import nutmeg.interfaces.cli as cli

    hits = _spy_after_settle(monkeypatch)
    _stub_settle(monkeypatch)
    CliRunner().invoke(cli.app, ["decision-settle", "--run-date", "2026-09-19",
                                 "--output-dir", str(tmp_path), "--dry-run"])
    assert hits == []


def test_decision_settle_calls_after_settle_when_not_dry_run(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import nutmeg.interfaces.cli as cli

    hits = _spy_after_settle(monkeypatch)
    _stub_settle(monkeypatch)
    result = CliRunner().invoke(cli.app, ["decision-settle", "--run-date", "2026-09-19",
                                          "--output-dir", str(tmp_path), "--no-dry-run"])
    assert result.exit_code == 0, result.output
    assert len(hits) == 1
    assert hits[0]["day"] == "2026-09-19"
    assert hits[0]["data_dir"] == tmp_path.parent
