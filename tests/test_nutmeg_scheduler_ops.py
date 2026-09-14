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


def _write_handoff(output_dir: Path, run_date: str, **overrides):
    day_dir = output_dir / "daily" / run_date
    day_dir.mkdir(parents=True)
    handoff = {
        "run_date": run_date,
        "status": "frozen",
        "position": "ready",
        "summary": "Reviewed",
        "read_ids": [],
        "questions": [],
        "explicit_empty_reason": "",
    }
    handoff.update(overrides)
    (day_dir / "nutmeg-handoff.json").write_text(json.dumps(handoff))
    return day_dir


def test_validate_preclose_ready(tmp_path, capsys):
    day_dir = _write_handoff(tmp_path, "2026-07-13")
    legs = [{
        "match_id": "M-1",
        "market": "hhad",
        "selection": "让胜",
        "odds": 1.95,
        "bucket": "main",
        "line": -1,
    }]
    (day_dir / "legs.json").write_text(json.dumps(legs))

    ops.validate_preclose("2026-07-13", tmp_path)

    assert "NUTMEG_GATE_OK" in capsys.readouterr().out


def test_validate_preclose_accepts_explicit_abstain(tmp_path):
    _write_handoff(
        tmp_path,
        "2026-07-13",
        position="abstain",
        explicit_empty_reason="No evidence-backed edge",
    )

    ops.validate_preclose("2026-07-13", tmp_path)


def test_validate_preclose_rejects_missing_hhad_line(tmp_path):
    day_dir = _write_handoff(tmp_path, "2026-07-13")
    legs = [{
        "match_id": "M-1",
        "market": "hhad",
        "selection": "让胜",
        "odds": 1.95,
        "bucket": "main",
    }]
    (day_dir / "legs.json").write_text(json.dumps(legs))

    try:
        ops.validate_preclose("2026-07-13", tmp_path)
    except ops.SchedulerError as exc:
        assert "line is required" in str(exc)
    else:
        raise AssertionError("missing hhad line should fail")


def test_validate_preclose_rejects_unfrozen_handoff(tmp_path):
    _write_handoff(tmp_path, "2026-07-13", status="provisional")

    try:
        ops.validate_preclose("2026-07-13", tmp_path)
    except ops.SchedulerError as exc:
        assert "not frozen" in str(exc)
    else:
        raise AssertionError("provisional handoff should fail")


def test_build_context_aggregates_previous_day(tmp_path):
    output_dir = tmp_path / "out"
    decision_dir = output_dir / "decision"
    decision_dir.mkdir(parents=True)
    (decision_dir / "reads.jsonl").write_text(
        json.dumps({"read_id": "R-1", "match_id": "M-2026-07-12-A-B"}) + "\n"
    )
    (decision_dir / "settlements.jsonl").write_text(json.dumps({
        "settlement_id": "S-1",
        "ref_id": "R-1",
        "ref_type": "read",
        "brier": 0.25,
        "clv_pp": 1.5,
    }) + "\n")
    day_dir = output_dir / "daily" / "2026-07-13"
    day_dir.mkdir(parents=True)
    (day_dir / "sporttery_markets.json").write_text(json.dumps({
        "lastUpdateTime": "2026-07-13 17:00:00",
        "totalCount": 1,
        "matchInfoList": [],
    }))

    path = ops.build_context("2026-07-13", output_dir, tmp_path / "logs")
    context = json.loads(path.read_text())

    assert context["previous_day"]["settlement_count"] == 1
    assert context["previous_day"]["average_brier"] == 0.25
    assert context["current_day"]["market_total_count"] == 1


def test_close_refuses_to_run_without_frozen_handoff(tmp_path, monkeypatch):
    commands = []
    events = []
    monkeypatch.setattr(ops, "_run", lambda command: commands.append(command))
    monkeypatch.setattr(
        ops, "_publish_operation_event", lambda **event: events.append(event)
    )

    with pytest.raises(ops.SchedulerError, match="missing file"):
        ops.run_strict(
            "close",
            "2026-07-17",
            tmp_path,
            operation_state_file=tmp_path / "operation-state.json",
        )

    assert commands == []
    assert [event["kind"] for event in events] == ["operations.failure"]
    assert events[0]["summary"] == (
        "今日决策未完成，收盘已安全停止；系统未将流程失败记为空仓。"
    )


def test_close_runs_after_frozen_handoff(tmp_path, monkeypatch):
    _write_handoff(
        tmp_path,
        "2026-07-17",
        position="abstain",
        explicit_empty_reason="No qualified position",
    )
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"status": "succeeded", "steps": []}),
        stderr="",
    )
    commands = []
    monkeypatch.setattr(ops, "_run", lambda command: commands.append(command) or completed)
    monkeypatch.setattr(ops, "_publish_operation_event", lambda **event: None)

    ops.run_strict(
        "close",
        "2026-07-17",
        tmp_path,
        operation_state_file=tmp_path / "operation-state.json",
    )

    assert len(commands) == 1
    assert "decision-close" in commands[0]


def test_run_strict_uses_structured_failure_and_publishes_event(tmp_path, monkeypatch):
    _write_handoff(
        tmp_path,
        "2026-07-17",
        position="abstain",
        explicit_empty_reason="No qualified position",
    )
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
            "close",
            "2026-07-17",
            tmp_path,
            operation_state_file=tmp_path / "operation-state.json",
        )

    assert commands[0][-2:] == ["--format", "json"]
    assert events[0]["kind"] == "operations.failure"
    assert events[0]["stage"] == "close"


def test_success_after_failure_publishes_recovery_once(tmp_path, monkeypatch):
    state_file = tmp_path / "operation-state.json"
    state_file.write_text(
        json.dumps({"close:2026-07-17": {"status": "failed"}}),
        encoding="utf-8",
    )
    events = []
    monkeypatch.setattr(
        ops, "_publish_operation_event", lambda **event: events.append(event)
    )

    ops._record_operation_success("close", "2026-07-17", state_file)
    ops._record_operation_success("close", "2026-07-17", state_file)

    assert [event["kind"] for event in events] == ["operations.recovered"]


def test_verify_close_uses_notification_ledger(tmp_path, monkeypatch, capsys):
    run_date = "2026-07-17"
    day_dir = _write_handoff(tmp_path, run_date)
    report = day_dir / f"decision-report-{run_date}.pdf"
    report.write_bytes(b"%PDF")
    monkeypatch.setattr(ops, "_has_sent_notification", lambda **kwargs: True)

    ops.verify_close(run_date, tmp_path, tmp_path / "logs")

    assert "NUTMEG_CLOSE_OK" in capsys.readouterr().out


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


# ── verify-close 与 close 的实际产物同步（2026-09-15）─────────────────────
#
# `Nutmeg-收盘交付确认`(19:10) 连错 11 次后于 2026-08-25 被禁用，**close 自此无人
# 审计地跑了三周**。根因是两处都在找早已不存在的东西：
#   · 产物：close 2026-08-23 之后改产 `decision-report-v2-<date>.md`，
#     最后一份 PDF 就是 08-23 那天的；verify 仍查 `decision-report-<date>.pdf`
#   · 通知 kind：close 现在发 `decision.close.report.v2`
#     (`ontology_adapter.py:629`)；verify 仍查旧的 `decision.close.report`
# 两处都改为**优先认 v2、兼容旧格式**（历史日期仍要可验）。


def test_verify_close_accepts_the_v2_markdown_report(tmp_path, monkeypatch, capsys):
    run_date = "2026-09-14"
    day_dir = _write_handoff(tmp_path, run_date)
    (day_dir / f"decision-report-v2-{run_date}.md").write_text("# 决策日报 v2", "utf-8")
    seen: list[str] = []

    def _ledger(**kwargs):
        seen.append(kwargs["kind"])
        return kwargs["kind"] == "decision.close.report.v2"

    monkeypatch.setattr(ops, "_has_sent_notification", _ledger)
    ops.verify_close(run_date, tmp_path, tmp_path / "logs")
    assert "NUTMEG_CLOSE_OK" in capsys.readouterr().out
    assert "decision.close.report.v2" in seen


def test_verify_close_still_accepts_the_legacy_pdf(tmp_path, monkeypatch, capsys):
    """历史日期（2026-08-23 及以前）仍要可验。"""
    run_date = "2026-08-21"
    day_dir = _write_handoff(tmp_path, run_date)
    (day_dir / f"decision-report-{run_date}.pdf").write_bytes(b"%PDF")

    def _ledger(**kwargs):
        return kwargs["kind"] == "decision.close.report"

    monkeypatch.setattr(ops, "_has_sent_notification", _ledger)
    ops.verify_close(run_date, tmp_path, tmp_path / "logs")
    assert "NUTMEG_CLOSE_OK" in capsys.readouterr().out


def test_verify_close_still_fails_when_no_report_exists(tmp_path, monkeypatch):
    """闸不能因为放宽格式就变成永远通过。"""
    run_date = "2026-09-14"
    _write_handoff(tmp_path, run_date)
    monkeypatch.setattr(ops, "_has_sent_notification", lambda **kwargs: True)
    with pytest.raises(ops.SchedulerError, match="report"):
        ops.verify_close(run_date, tmp_path, tmp_path / "logs")


def test_verify_close_still_fails_when_the_ledger_has_no_delivery(tmp_path, monkeypatch):
    run_date = "2026-09-14"
    day_dir = _write_handoff(tmp_path, run_date)
    (day_dir / f"decision-report-v2-{run_date}.md").write_text("# 决策日报 v2", "utf-8")
    monkeypatch.setattr(ops, "_has_sent_notification", lambda **kwargs: False)
    with pytest.raises(ops.SchedulerError, match="ledger"):
        ops.verify_close(run_date, tmp_path, tmp_path / "logs")
