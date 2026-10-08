import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "openclaw" / "nutmeg_scheduler_ops.py"
SPEC = importlib.util.spec_from_file_location("nutmeg_scheduler_ops", SCRIPT)
ops = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ops)


def test_build_context_writes_current_day_board(tmp_path):
    output_dir = tmp_path / "out"
    day_dir = output_dir / "daily" / "2026-07-13"
    day_dir.mkdir(parents=True)
    (day_dir / "sporttery_markets.json").write_text(json.dumps({
        "lastUpdateTime": "2026-07-13 17:00:00",
        "totalCount": 1,
        "matchInfoList": [{"subMatchList": [{
            "businessDate": "2026-07-13", "matchNumStr": "周一001", "leagueAbbName": "瑞超",
            "homeTeamAbbName": "哈马比", "awayTeamAbbName": "卡尔马",
            "matchTime": "19:00:00", "matchStatus": "Selling"}]}],
    }))

    path = ops.build_context("2026-07-13", output_dir)
    context = json.loads(path.read_text())

    assert context["run_date"] == "2026-07-13" and context["previous_date"] == "2026-07-12"
    assert "previous_day" not in context      # 停写的 v1 JSONL 聚合已删（2026-10-08）
    assert context["current_day"]["market_total_count"] == 1
    assert [f["match_num"] for f in context["current_day"]["fixtures"]] == ["周一001"]


def test_run_strict_uses_structured_failure_and_publishes_event(tmp_path, monkeypatch):
    payload = {
        "status": "failed",
        "steps": [
            {"label": "report", "status": "failed", "message": "render failed"}
        ],
    }
    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=json.dumps(payload), stderr=""
    )
    commands = []
    events = []
    monkeypatch.setattr(ops, "_run", lambda command: commands.append(command) or completed)
    monkeypatch.setattr(
        ops, "_publish_operation_event", lambda **event: events.append(event)
    )

    with pytest.raises(ops.SchedulerError, match="report: render failed"):
        ops.run_strict(
            "am",
            "2026-07-17",
            tmp_path,
            operation_state_file=tmp_path / "operation-state.json",
        )

    assert commands[0][-2:] == ["--format", "json"]
    assert events[0]["kind"] == "operations.failure"
    assert events[0]["stage"] == "am"


def test_success_after_failure_publishes_recovery_once(tmp_path, monkeypatch):
    state_file = tmp_path / "operation-state.json"
    state_file.write_text(
        json.dumps({"am:2026-07-17": {"status": "failed"}}),
        encoding="utf-8",
    )
    events = []
    monkeypatch.setattr(
        ops, "_publish_operation_event", lambda **event: events.append(event)
    )

    ops._record_operation_success("am", "2026-07-17", state_file)
    ops._record_operation_success("am", "2026-07-17", state_file)

    assert [event["kind"] for event in events] == ["operations.recovered"]


def test_run_strict_records_post_stage_context_failure(tmp_path, monkeypatch):
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"status": "succeeded", "steps": []}),
        stderr="",
    )
    events = []
    monkeypatch.setattr(ops, "_run", lambda command: completed)
    monkeypatch.setattr(
        ops,
        "build_context",
        lambda *args: (_ for _ in ()).throw(ops.SchedulerError("context failed")),
    )
    monkeypatch.setattr(
        ops, "_publish_operation_event", lambda **event: events.append(event)
    )

    with pytest.raises(ops.SchedulerError, match="context failed"):
        ops.run_strict(
            "am",
            "2026-07-17",
            tmp_path,
            operation_state_file=tmp_path / "operation-state.json",
        )

    assert [event["kind"] for event in events] == ["operations.failure"]


def test_operation_failure_summary_redacts_secret_like_values() -> None:
    summary = ops._safe_summary(
        "POST /bot123456:ABC/sendDocument?api_key=topsecret "
        "NUTMEG_TELEGRAM_BOT_TOKEN=anothersecret"
    )

    assert "topsecret" not in summary
    assert "anothersecret" not in summary
    assert "123456:ABC" not in summary



def _fake_am(monkeypatch, message: str, other_failed: bool = False):
    steps = [{"label": "fetch", "status": "failed", "message": f"失败 — {message}"},
             {"label": "sense", "status": "succeeded", "message": "空盘(合法)"}]
    if other_failed:
        steps.append({"label": "report", "status": "failed", "message": "render failed"})
    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=json.dumps({"status": "failed", "steps": steps}), stderr="")
    monkeypatch.setattr(ops, "_run", lambda command: completed)
    monkeypatch.setattr(ops, "_publish_operation_event", lambda **event: None)
    monkeypatch.setattr(ops, "build_context", lambda *a, **k: None)


def test_fully_empty_sporttery_list_is_a_legal_empty_board(tmp_path, monkeypatch, capsys):
    _fake_am(monkeypatch, ops.EMPTY_BOARD_MARK)
    ops.run_strict("am", "2026-10-02", tmp_path,
                   operation_state_file=tmp_path / "operation-state.json")
    assert "NUTMEG_OK stage=am run_date=2026-10-02 empty_board" in capsys.readouterr().out


def test_list_with_nothing_on_sale_yet_is_a_legal_empty_board(tmp_path, monkeypatch, capsys):
    """2026-10-05：「0 在售 / N 未开售」＝体彩自己说一场都没开售（周一板 11:00 才开售、
    假期次日板提前挂出）。重试与告警都换不来任何东西，开售后 11:00/14:00 备料入库与 17:15
    刷新会抓到；按故障推送只制造了 10-01/10-02/10-04 的「am degraded」与 OpenClaw cron 报错。"""
    _fake_am(monkeypatch, "Sporttery calculator empty (not a WAF block): "
                          "match list 0 Selling / 31 not yet on sale")
    ops.run_strict("am", "2026-10-04", tmp_path,
                   operation_state_file=tmp_path / "operation-state.json")
    assert "NUTMEG_OK stage=am run_date=2026-10-04 empty_board" in capsys.readouterr().out


def test_calculator_glitch_while_on_sale_or_other_failures_still_fail(tmp_path, monkeypatch):
    _fake_am(monkeypatch, "Sporttery calculator empty (not a WAF block): "
                          "match list 1 Selling / 8 not yet on sale")
    with pytest.raises(ops.SchedulerError, match="degraded"):
        ops.run_strict("am", "2026-10-02", tmp_path,
                       operation_state_file=tmp_path / "operation-state.json")
    _fake_am(monkeypatch, "Sporttery returned no matchInfoList (degraded/WAF response)")
    with pytest.raises(ops.SchedulerError, match="degraded"):
        ops.run_strict("am", "2026-10-02", tmp_path,
                       operation_state_file=tmp_path / "operation-state.json")
    _fake_am(monkeypatch, ops.EMPTY_BOARD_MARK, other_failed=True)
    with pytest.raises(ops.SchedulerError, match="render failed"):
        ops.run_strict("am", "2026-10-02", tmp_path,
                       operation_state_file=tmp_path / "operation-state.json")
