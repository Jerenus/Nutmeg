"""Explicit local reliability evidence, recovery, and release operations."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole, ObjectRef, canonical_json
from nutmeg.ontology.actions.reliability_actions import (
    ApproveReleaseRequest,
    RecordReliabilityEvidenceRequest,
)
from nutmeg.ontology.errors import OntologyError
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.reliability.backup import RecoveryError, create_backup, run_restore_drill
from nutmeg.reliability.contracts import validate_evidence_report
from nutmeg.reliability.release import ReleaseEvaluator
from nutmeg.reliability.scheduler import inspect_scheduler_authority

reliability_app = _cli.typer.Typer(help="Reliability and release governance")
_cli.app.add_typer(reliability_app, name="reliability")

_DATA_DIR = _cli.typer.Option(..., "--data-dir")
_REQUESTED_AT = _cli.typer.Option(..., "--requested-at")
_REPORT_FILE = _cli.typer.Option(..., "--report-file")
_DESTINATION = _cli.typer.Option(..., "--destination")
_BACKUP_DIR = _cli.typer.Option(..., "--backup-dir")
_RESTORE_DATA_DIR = _cli.typer.Option(..., "--restore-data-dir")
_PLIST_PATHS = _cli.typer.Option(..., "--plist")
_RUNTIME_REPORT = _cli.typer.Option(..., "--runtime-report")
_SOP_FILES = _cli.typer.Option(..., "--sop-file")
_PROJECT_ROOT = _cli.typer.Option(..., "--project-root")


def _emit(document: dict[str, object]) -> None:
    _cli.typer.echo(canonical_json(document))


def _fail(error: Exception) -> None:
    _emit({"code": "reliability_operation_blocked", "message": str(error)})
    raise _cli.typer.Exit(code=1)


def _at(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _kernel(data_dir: Path):
    resolved = Path(data_dir).expanduser().resolve()
    kernel = _cli.build_ontology_kernel(AppSettings(data_dir=resolved))
    status = kernel.status()
    if not status.initialized or status.integrity_check != "ok" or status.pending_migrations:
        raise ValueError("ontology must be initialized, healthy, and current")
    return kernel, resolved


def _read_report(path: Path) -> tuple[Path, dict[str, object], str]:
    resolved = Path(path).expanduser().resolve()
    content = resolved.read_bytes()
    try:
        report = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("report file must contain valid JSON") from error
    if not isinstance(report, dict):
        raise ValueError("report file must contain a JSON object")
    return resolved, report, hashlib.sha256(content).hexdigest()


def _outcome(outcome, *, targets: dict[str, object]) -> dict[str, object]:
    return {
        "action_id": outcome.action_id,
        "action_type": outcome.action_type,
        "status": outcome.status.value,
        "result_refs": [ref.to_dict() for ref in outcome.result_refs],
        "error_code": outcome.error_code,
        "targets": targets,
    }


def _evaluation_document(evaluation) -> dict[str, object]:
    return {
        "release_version": evaluation.release_version,
        "candidate_commit": evaluation.candidate_commit,
        "policy_version": evaluation.policy_version,
        "evaluated_at": evaluation.evaluated_at,
        "ready": evaluation.ready,
        "gates": [gate.to_dict() for gate in evaluation.gates.values()],
        "soak_coverage": [
            coverage.to_dict() for coverage in evaluation.soak_coverage.values()
        ],
        "selected_evidence": [
            {
                "reliability_evidence_id": row.reliability_evidence_id,
                "evidence_kind": row.evidence_kind,
                "workflow": row.workflow,
                "business_date": row.business_date,
                "status": row.status,
                "content_hash": row.content_hash,
                "recorded_at": row.recorded_at,
            }
            for row in evaluation.selected_evidence
        ],
        "evidence_snapshot_sha256": evaluation.evidence_snapshot_sha256,
        "approval_status": evaluation.approval_status,
    }


@reliability_app.command("status")
def reliability_status(
    data_dir: Path = _DATA_DIR,
    release_version: str = _cli.typer.Option(..., "--release-version"),
    candidate_commit: str = _cli.typer.Option(..., "--candidate-commit"),
    evaluated_at: str = _cli.typer.Option(..., "--evaluated-at"),
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        with OntologyUnitOfWork(kernel.engine) as uow:
            evaluation = ReleaseEvaluator(uow.reliability).evaluate(
                release_version,
                candidate_commit=candidate_commit,
                evaluated_at=_at(evaluated_at, "evaluated_at"),
            )
        document = _evaluation_document(evaluation)
        document["targets"] = {
            "data_dir": str(resolved),
            "ontology_db": str(kernel.paths.database.resolve()),
        }
        _emit(document)
    except (OSError, OntologyError, ValueError) as error:
        _fail(error)


@reliability_app.command("record")
def reliability_record(
    data_dir: Path = _DATA_DIR,
    kind: str = _cli.typer.Option(..., "--kind"),
    report_file: Path = _REPORT_FILE,
    observed_from: str = _cli.typer.Option(..., "--observed-from"),
    observed_to: str = _cli.typer.Option(..., "--observed-to"),
    requested_at: str = _REQUESTED_AT,
    workflow: str = _cli.typer.Option("system", "--workflow"),
    business_date: str | None = _cli.typer.Option(None, "--business-date"),
    acknowledge: bool = _cli.typer.Option(False, "--acknowledge"),
) -> None:
    try:
        if not acknowledge:
            raise ValueError("record requires --acknowledge")
        kernel, resolved = _kernel(data_dir)
        report_path, report, report_hash = _read_report(report_file)
        validation = validate_evidence_report(kind, report)
        status = "passed" if validation.passed else "failed"
        observed_from_at = _at(observed_from, "observed_from")
        observed_to_at = _at(observed_to, "observed_to")
        requested_at_at = _at(requested_at, "requested_at")
        identity = {
            "business_date": business_date,
            "evidence_kind": kind,
            "observed_from": observed_from_at.isoformat(),
            "observed_to": observed_to_at.isoformat(),
            "report_sha256": report_hash,
            "workflow": workflow,
        }
        identity_hash = hashlib.sha256(
            canonical_json(identity).encode("utf-8")
        ).hexdigest()
        request = RecordReliabilityEvidenceRequest(
            evidence_kind=kind,
            workflow=workflow,
            business_date=business_date,
            observed_from=observed_from_at,
            observed_to=observed_to_at,
            status=status,
            report=report,
            source_refs=[ObjectRef("report_file_sha256", report_hash)],
            actor_id="operator:reliability-record",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"reliability:record:{identity_hash}",
            requested_at=requested_at_at,
        )
        outcome = kernel.reliability_actions.record_evidence(request)
        _emit(
            _outcome(
                outcome,
                targets={
                    "data_dir": str(resolved),
                    "ontology_db": str(kernel.paths.database.resolve()),
                    "report_file": str(report_path),
                },
            )
        )
    except (OSError, OntologyError, ValueError) as error:
        _fail(error)


@reliability_app.command("backup-create")
def reliability_backup_create(
    data_dir: Path = _DATA_DIR,
    destination: Path = _DESTINATION,
    requested_at: str = _REQUESTED_AT,
    acknowledge_writers_stopped: bool = _cli.typer.Option(
        False, "--acknowledge-writers-stopped"
    ),
) -> None:
    try:
        kernel, resolved = _kernel(data_dir)
        target = Path(destination).expanduser().resolve()
        result = create_backup(
            kernel,
            target,
            requested_at=_at(requested_at, "requested_at"),
            acknowledge_writers_stopped=acknowledge_writers_stopped,
        )
        _emit(
            {
                "status": "created",
                "manifest_sha256": result.manifest_sha256,
                "schema_version": result.manifest["schema_version"],
                "action_high_watermark": result.manifest["action_high_watermark"],
                "outbox_cursor": result.manifest["outbox_cursor"],
                "targets": {
                    "data_dir": str(resolved),
                    "destination": str(target),
                    "manifest": str(result.manifest_path),
                },
            }
        )
    except (OSError, RecoveryError, ValueError) as error:
        _fail(error)


@reliability_app.command("restore-drill")
def reliability_restore_drill(
    backup_dir: Path = _BACKUP_DIR,
    restore_data_dir: Path = _RESTORE_DATA_DIR,
    requested_at: str = _REQUESTED_AT,
) -> None:
    try:
        source = Path(backup_dir).expanduser().resolve()
        target = Path(restore_data_dir).expanduser().resolve()
        report = run_restore_drill(
            source,
            target,
            requested_at=_at(requested_at, "requested_at"),
        )
        _emit(
            {
                "status": report.status,
                "source_manifest_sha256": report.source_manifest_sha256,
                "action_high_watermark": report.action_high_watermark,
                "outbox_cursor": report.outbox_cursor,
                "projection_high_watermark": report.projection_high_watermark,
                "targets": {
                    "backup_dir": str(source),
                    "restore_data_dir": str(target),
                },
            }
        )
    except (OSError, RecoveryError, ValueError) as error:
        _fail(error)


@reliability_app.command("scheduler-review")
def reliability_scheduler_review(
    data_dir: Path = _DATA_DIR,
    plist_paths: list[Path] = _PLIST_PATHS,
    runtime_report: Path = _RUNTIME_REPORT,
    sop_files: list[Path] = _SOP_FILES,
    project_root: Path = _PROJECT_ROOT,
    requested_at: str = _REQUESTED_AT,
    acknowledge: bool = _cli.typer.Option(False, "--acknowledge"),
) -> None:
    try:
        if not acknowledge:
            raise ValueError("scheduler-review requires --acknowledge")
        kernel, resolved = _kernel(data_dir)
        resolved_plists = [Path(path).expanduser().resolve() for path in plist_paths]
        resolved_sops = [Path(path).expanduser().resolve() for path in sop_files]
        runtime_path = Path(runtime_report).expanduser().resolve()
        root = Path(project_root).expanduser().resolve()
        at = _at(requested_at, "requested_at")
        review = inspect_scheduler_authority(
            kernel=kernel,
            plist_paths=resolved_plists,
            runtime_report_path=runtime_path,
            sop_paths=resolved_sops,
            expected_project_root=root,
            requested_at=at,
        )
        source_paths = [*resolved_plists, runtime_path, *resolved_sops]
        source_refs = [
            ObjectRef("file_sha256", hashlib.sha256(path.read_bytes()).hexdigest())
            for path in source_paths
        ]
        evidence_report = review.to_evidence_report()
        digest = hashlib.sha256(
            canonical_json(evidence_report).encode("utf-8")
        ).hexdigest()
        outcome = kernel.reliability_actions.record_evidence(
            RecordReliabilityEvidenceRequest(
                evidence_kind="scheduler_authority",
                workflow="system",
                business_date=None,
                observed_from=at,
                observed_to=at,
                status="passed" if review.passed else "failed",
                report=evidence_report,
                source_refs=source_refs,
                actor_id="operator:scheduler-review",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"reliability:scheduler:{digest}",
                requested_at=at,
            )
        )
        document = _outcome(
            outcome,
            targets={
                "data_dir": str(resolved),
                "ontology_db": str(kernel.paths.database.resolve()),
                "plist_files": [str(path) for path in resolved_plists],
                "runtime_report": str(runtime_path),
                "sop_files": [str(path) for path in resolved_sops],
            },
        )
        document["review"] = review.to_dict()
        _emit(document)
    except (OSError, OntologyError, ValueError) as error:
        _fail(error)


@reliability_app.command("approve-release")
def reliability_approve_release(
    data_dir: Path = _DATA_DIR,
    release_version: str = _cli.typer.Option(..., "--release-version"),
    candidate_commit: str = _cli.typer.Option(..., "--candidate-commit"),
    expected_snapshot: str = _cli.typer.Option(..., "--expected-snapshot"),
    reason: str = _cli.typer.Option(..., "--reason"),
    requested_at: str = _REQUESTED_AT,
    approve: bool = _cli.typer.Option(False, "--approve"),
) -> None:
    try:
        if not approve:
            raise ValueError("approve-release requires --approve")
        kernel, resolved = _kernel(data_dir)
        outcome = kernel.reliability_actions.approve_release(
            ApproveReleaseRequest(
                release_version=release_version,
                candidate_commit=candidate_commit,
                expected_snapshot_sha256=expected_snapshot,
                reason=reason,
                actor_id="operator:jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=(
                    f"reliability:approve:{release_version}:{expected_snapshot}"
                ),
                requested_at=_at(requested_at, "requested_at"),
            )
        )
        _emit(
            _outcome(
                outcome,
                targets={
                    "data_dir": str(resolved),
                    "ontology_db": str(kernel.paths.database.resolve()),
                    "release_version": release_version,
                },
            )
        )
    except (OSError, OntologyError, ValueError) as error:
        _fail(error)
