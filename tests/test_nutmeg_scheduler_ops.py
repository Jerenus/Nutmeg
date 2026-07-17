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
