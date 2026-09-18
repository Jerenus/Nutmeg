"""接线只加一行：备料链跑完 → rsi schedule + due；观察仪落盘 → rsi fulfill。用假 invoker 验参数。"""
from nutmeg.decision.rsi_wiring import after_observation_artifact, after_prep


def test_after_prep_schedules_then_lists_due(tmp_path):
    calls = []
    after_prep(issue="26129", day="2026-09-19", data_dir=tmp_path,
               invoke=lambda argv: calls.append(argv) or 0)
    assert calls[0][:2] == ["rsi", "schedule"] and "--issue" in calls[0] and "26129" in calls[0]
    assert calls[1][:2] == ["rsi", "due"]


def test_after_observation_artifact_fulfills_with_row_count(tmp_path):
    calls = []
    art = tmp_path / "26129-f2-observation.json"
    art.write_text('{"observations": {"1": {}, "2": {}}}')
    after_observation_artifact(exp="F2", duty="f2-observation", issue="26129", day="2026-09-19",
                               artifact=art, n_rows=2, data_dir=tmp_path,
                               invoke=lambda argv: calls.append(argv) or 0)
    assert calls[0][:2] == ["rsi", "fulfill"] and "--n-rows" in calls[0] and "2" in calls[0]


def test_cli_invoke_never_raises_on_failure(tmp_path, capsys):
    """登记失败只打印警告并返回非零——绝不能让备料链/观察仪的主任务跟着失败。"""
    from nutmeg.decision.rsi_wiring import _cli_invoke

    # 不存在的 issue.json → `rsi schedule` 以退出码 1 结束；接线层必须吞掉而非抛出。
    rc = _cli_invoke(["rsi", "schedule", "--day", "2026-09-19", "--issue", "99999",
                      "--data-dir", str(tmp_path / "data")])
    assert rc != 0
    assert "rsi 接线未成功" in capsys.readouterr().out
