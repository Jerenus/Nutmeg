import json
import plistlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.wiring import build_ontology_kernel

NOW = "2026-08-24T12:00:00+00:00"


def _invoke(*args: str):
    return CliRunner().invoke(app, ["reliability", *args])


def _json(result):
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert result.stdout.strip() == canonical_json(payload)
    return payload


def test_reliability_status_and_record_are_explicit_and_canonical(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    status = _json(
        _invoke(
            "status",
            "--data-dir",
            str(data_dir),
            "--release-version",
            "v1.0.0",
            "--candidate-commit",
            "abc123",
            "--evaluated-at",
            NOW,
        )
    )
    assert status["ready"] is False
    assert status["targets"]["data_dir"] == str(data_dir.resolve())
    assert status["gates"][0]["gate_id"] == "G1"

    report_file = tmp_path / "deterministic.json"
    report_file.write_text(
        json.dumps(
            {
                "candidate_commit": "abc123",
                "policy_version": "release-v1",
                "checks": {"pytest": True},
            }
        ),
        encoding="utf-8",
    )
    base = (
        "record",
        "--data-dir",
        str(data_dir),
        "--kind",
        "deterministic_suite",
        "--report-file",
        str(report_file),
        "--observed-from",
        "2026-08-24T11:00:00+00:00",
        "--observed-to",
        NOW,
        "--requested-at",
        NOW,
    )
    assert _invoke(*base).exit_code != 0
    recorded = _json(_invoke(*base, "--acknowledge"))
    assert recorded["status"] == "committed"
    assert recorded["targets"]["report_file"] == str(report_file.resolve())
    assert recorded["targets"]["ontology_db"] == str(
        (data_dir / "ontology" / "ontology.db").resolve()
    )


def test_reliability_record_scopes_idempotency_to_soak_workflow(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    report_file = tmp_path / "soak.json"
    report_file.write_text(
        json.dumps(
            {
                "schema_version": "soak-v1",
                "policy_version": "release-v1",
                "dispatch": False,
                "synthetic": False,
                "divergences": {"identity": 0, "audit": 0, "ledger": 0},
            }
        ),
        encoding="utf-8",
    )
    common = (
        "record",
        "--data-dir",
        str(data_dir),
        "--kind",
        "soak_run",
        "--report-file",
        str(report_file),
        "--business-date",
        "2026-08-24",
        "--observed-from",
        "2026-08-24T11:00:00+00:00",
        "--observed-to",
        NOW,
        "--requested-at",
        NOW,
        "--acknowledge",
    )

    jczq = _json(_invoke(*common, "--workflow", "jczq"))
    zucai = _json(_invoke(*common, "--workflow", "zucai"))

    assert jczq["status"] == zucai["status"] == "committed"
    assert jczq["action_id"] != zucai["action_id"]
    assert kernel.status().reliability_evidence_count == 2


def test_reliability_backup_restore_and_blocked_approval_are_guarded(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    backup_dir = tmp_path / "backup"
    backup_args = (
        "backup-create",
        "--data-dir",
        str(data_dir),
        "--destination",
        str(backup_dir),
        "--requested-at",
        NOW,
    )
    assert _invoke(*backup_args).exit_code != 0
    backup = _json(_invoke(*backup_args, "--acknowledge-writers-stopped"))
    assert backup["status"] == "created"
    assert backup["targets"]["destination"] == str(backup_dir.resolve())

    restore_dir = tmp_path / "restored"
    restored = _json(
        _invoke(
            "restore-drill",
            "--backup-dir",
            str(backup_dir),
            "--restore-data-dir",
            str(restore_dir),
            "--requested-at",
            NOW,
        )
    )
    assert restored["status"] == "passed"
    assert restored["targets"]["restore_data_dir"] == str(restore_dir.resolve())

    blocked = _invoke(
        "approve-release",
        "--data-dir",
        str(data_dir),
        "--release-version",
        "v1.0.0",
        "--candidate-commit",
        "abc123",
        "--expected-snapshot",
        "a" * 64,
        "--reason",
        "manual review",
        "--requested-at",
        NOW,
        "--approve",
    )
    assert blocked.exit_code != 0


def test_reliability_cli_requires_paths_and_aware_timestamps() -> None:
    assert _invoke("status").exit_code == 2
    result = _invoke(
        "status",
        "--data-dir",
        "/does/not/exist",
        "--release-version",
        "v1",
        "--candidate-commit",
        "abc",
        "--evaluated-at",
        datetime(2026, 8, 24, 12, tzinfo=UTC).replace(tzinfo=None).isoformat(),
    )
    assert result.exit_code != 0


def test_scheduler_review_cli_records_sanitized_failed_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "schema_version": "scheduler-runtime-v1",
                "candidate_commit": "abc123",
                "loaded_labels": [
                    "com.nutmeg.decision.am",
                    "com.nutmeg.decision.close",
                    "com.nutmeg.decision.settle",
                ],
                "effective_environment": {
                    "NUTMEG_ONTOLOGY_V2": "1",
                    "SECRET": "must-not-leak",
                },
            }
        ),
        encoding="utf-8",
    )
    sop_root = tmp_path / "sop"
    shutil.copytree(Path("tests/fixtures/m5/sop"), sop_root)
    project_root = tmp_path / "project"
    plist_root = tmp_path / "plists"
    plist_root.mkdir()
    labels = {
        "am": ("com.nutmeg.decision.am", 8, 0),
        "close": ("com.nutmeg.decision.close", 19, 0),
        "settle": ("com.nutmeg.decision.settle", 8, 10),
    }
    plist_paths = []
    for stage, (label, hour, minute) in labels.items():
        path = plist_root / f"{label}.plist"
        with path.open("wb") as handle:
            plistlib.dump(
                {
                    "Label": label,
                    "ProgramArguments": [
                        "/bin/zsh",
                        "-lc",
                        (
                            "uv run python scripts/openclaw/nutmeg_scheduler_ops.py "
                            f"run-strict --stage {stage}"
                        ),
                    ],
                    "StartCalendarInterval": {"Hour": hour, "Minute": minute},
                    "StandardOutPath": str(
                        project_root / ".nutmeg-data" / "logs" / f"{stage}.out.log"
                    ),
                    "StandardErrorPath": str(
                        project_root / ".nutmeg-data" / "logs" / f"{stage}.err.log"
                    ),
                    "WorkingDirectory": str(project_root),
                },
                handle,
            )
        plist_paths.append(path)
    args = [
        "scheduler-review",
        "--data-dir",
        str(data_dir),
        "--runtime-report",
        str(runtime),
        "--project-root",
        str(project_root),
        "--requested-at",
        NOW,
    ]
    for path in plist_paths:
        args.extend(["--plist", str(path)])
    for name in ("CONSTITUTION.md", "RUNBOOK.md", "RULEBOOK.md", "AGENTS.md", "CLAUDE.md"):
        args.extend(["--sop-file", str(sop_root / name)])

    assert _invoke(*args).exit_code != 0
    reviewed = _json(_invoke(*args, "--acknowledge"))

    assert reviewed["status"] == "committed"
    assert reviewed["review"]["passed"] is False
    assert "scoreboard_authority_not_ontology" in reviewed["review"]["issues"]
    assert "must-not-leak" not in canonical_json(reviewed)
    assert reviewed["targets"]["runtime_report"] == str(runtime.resolve())


def test_reliability_approve_failure_retry_exits_nonzero(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    args = (
        "approve-release",
        "--data-dir",
        str(data_dir),
        "--release-version",
        "v1.0.0",
        "--candidate-commit",
        "abc123",
        "--expected-snapshot",
        "0" * 64,
        "--reason",
        "blocked-approve-retry",
        "--requested-at",
        NOW,
        "--approve",
    )
    first = _invoke(*args)
    assert first.exit_code == 1                 # gates blocked -> failed attempt
    second = _invoke(*args)                     # identical retry must not turn green
    assert second.exit_code == 1
    assert '"status":"committed"' not in second.stdout


def test_emit_outcome_exits_nonzero_for_noncommitted_outcome() -> None:
    import click
    import pytest

    from nutmeg.interfaces.cli import reliability as reliability_cli
    from nutmeg.ontology.actions.models import ActionOutcome, ActionStatus

    outcome = ActionOutcome(
        action_id="ACT-rejected",
        action_type="record_reliability_evidence",
        status=ActionStatus.REJECTED,
        error_code="permission_denied",
    )
    with pytest.raises(click.exceptions.Exit) as excinfo:
        reliability_cli._emit_outcome(outcome, targets={})
    assert excinfo.value.exit_code == 1


def test_reliability_cli_rejects_future_timestamps(tmp_path: Path) -> None:
    from datetime import timedelta

    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    report_file = tmp_path / "det.json"
    report_file.write_text(
        json.dumps(
            {
                "schema_version": "deterministic_suite-v1",
                "candidate_commit": "abc123",
                "policy_version": "release-v1",
                "checks": {"pytest_full": True, "ruff": True, "compileall": True},
            }
        ),
        encoding="utf-8",
    )

    status = _invoke(
        "status", "--data-dir", str(data_dir), "--release-version", "v1.0.0",
        "--candidate-commit", "abc123", "--evaluated-at", future,
    )
    assert status.exit_code == 1
    assert "future" in status.stdout

    record = _invoke(
        "record", "--data-dir", str(data_dir), "--kind", "deterministic_suite",
        "--report-file", str(report_file),
        "--observed-from", NOW, "--observed-to", future,
        "--requested-at", NOW, "--acknowledge",
    )
    assert record.exit_code == 1
    assert "future" in record.stdout

    approve = _invoke(
        "approve-release", "--data-dir", str(data_dir),
        "--release-version", "v1.0.0", "--candidate-commit", "abc123",
        "--expected-snapshot", "0" * 64, "--reason", "x",
        "--requested-at", future, "--approve",
    )
    assert approve.exit_code == 1
    assert "future" in approve.stdout


def test_reliability_cli_rejects_future_soak_business_date(tmp_path: Path) -> None:
    from datetime import timedelta

    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    soak_file = tmp_path / "soak.json"
    soak_file.write_text(
        json.dumps(
            {
                "schema_version": "soak-v1",
                "policy_version": "release-v1",
                "dispatch": False,
                "synthetic": False,
                "divergences": {"identity": 0, "audit": 0, "ledger": 0},
            }
        ),
        encoding="utf-8",
    )
    future_date = (datetime.now(UTC) + timedelta(days=3)).strftime("%Y-%m-%d")
    soak = _invoke(
        "record", "--data-dir", str(data_dir), "--kind", "soak_run",
        "--report-file", str(soak_file), "--workflow", "jczq",
        "--business-date", future_date,
        "--observed-from", "2026-08-24T11:00:00+00:00", "--observed-to", NOW,
        "--requested-at", NOW, "--acknowledge",
    )
    assert soak.exit_code == 1
    assert "future" in soak.stdout
