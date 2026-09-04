"""Workflow object ingestion: rx 散文 → typed Actions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.decision.rx_ingest import map_rx_adjudications, map_rx_predictions
from nutmeg.ontology.actions.models import ActorRole, canonical_json
from nutmeg.ontology.actions.workflow_actions import (
    GradePredictionRequest,
    RecordAdjudicationRequest,
    RegisterPredictionRequest,
)
from nutmeg.ontology.operator.evidence_actions import IngestOperatorEvidenceRequest
from nutmeg.ontology.operator.evidence_manifest import EvidenceIntakeManifestV1
from nutmeg.ontology.operator.sale_actions import (
    ImportOfficialSaleSlateRequest,
    OfficialSaleSlateManifestV1,
    OfficialScheduleCheckManifestV1,
    RecordOfficialScheduleCheckRequest,
)
from nutmeg.ontology.repository import schema_operator_sale as sos
from nutmeg.product.operator_legacy_import import (
    LegacyOperatorImporter,
    LegacyQuarantineReport,
)

workflow_app = _cli.typer.Typer(help="rx 对象化与预测判定")
_cli.app.add_typer(workflow_app, name="workflow")

_DATA_DIR_OPTION = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_RX_FILE_OPTION = _cli.typer.Option(..., "--rx-file")
_MANIFEST_OPTION = _cli.typer.Option(..., "--manifest")
_CONTRACT_VERSION_OPTION = _cli.typer.Option(..., "--contract-version")


class WorkflowOperationError(RuntimeError):
    """Raised when a workflow CLI operation cannot proceed."""


def _kernel(data_dir: Path):
    resolved = Path(data_dir).expanduser().resolve()
    kernel = _cli.build_ontology_kernel(AppSettings(data_dir=resolved))
    status = kernel.status()
    if not status.initialized or status.integrity_check != "ok" or status.pending_migrations:
        raise WorkflowOperationError("ontology must be initialized, healthy, and current")
    return kernel


def _fail(error: Exception) -> None:
    _cli.typer.echo(canonical_json({"code": "workflow_operation_blocked", "message": str(error)}))
    raise _cli.typer.Exit(code=1)


def _now() -> datetime:
    return datetime.now(UTC)


def _manifest_document(
    manifest: Path,
    *,
    contract_version: str,
    expected_version: str,
) -> tuple[dict[str, object], str]:
    if contract_version != expected_version:
        raise WorkflowOperationError(f"contract version must be exactly {expected_version}")
    document = json.loads(Path(manifest).expanduser().read_text("utf-8"))
    if not isinstance(document, dict):
        raise WorkflowOperationError("manifest root must be a JSON object")
    digest = hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()
    return document, digest


@workflow_app.command("ingest-official-sale")
def ingest_official_sale(
    manifest: Path = _MANIFEST_OPTION,
    contract_version: str = _CONTRACT_VERSION_OPTION,
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    """Import one fully resolved official sale manifest through a typed Action."""
    try:
        document, digest = _manifest_document(
            manifest,
            contract_version=contract_version,
            expected_version="official-sale-slate-v1",
        )
        parsed = OfficialSaleSlateManifestV1.model_validate(document)
        kernel = _kernel(data_dir)
        result = kernel.sale_actions.import_official_sale_slate(
            ImportOfficialSaleSlateRequest(
                manifest=parsed,
                actor_id="system:official-sale",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"official-sale-slate-v1:{digest}",
                requested_at=_now(),
            )
        )
        if not result.outcome.status.is_success or result.slate is None:
            raise WorkflowOperationError(
                result.outcome.error_detail or result.outcome.error_code or "sale import rejected"
            )
        with kernel.engine.connect() as connection:
            slate_count = connection.scalar(
                select(func.count())
                .select_from(sos.official_sale_slate_revisions)
                .where(
                    sos.official_sale_slate_revisions.c.slate_revision_id
                    == result.slate.slate_revision_id
                )
            )
            family_count = connection.scalar(
                select(
                    func.count(
                        func.distinct(sos.official_offer_revisions.c.official_offer_family_id)
                    )
                ).where(
                    sos.official_offer_revisions.c.slate_revision_id
                    == result.slate.slate_revision_id
                )
            )
            offer_count = connection.scalar(
                select(func.count())
                .select_from(sos.official_offer_revisions)
                .where(
                    sos.official_offer_revisions.c.slate_revision_id
                    == result.slate.slate_revision_id
                )
            )
        _cli.typer.echo(
            canonical_json(
                {
                    "contract_version": "official-sale-slate-v1",
                    "action_id": result.outcome.action_id,
                    "status": result.outcome.status.value,
                    "lane": result.slate.lane,
                    "business_key": result.slate.business_key,
                    "slate_revision_id": result.slate.slate_revision_id,
                    "revision_no": result.slate.revision_no,
                    "created_counts": {
                        "slate_revisions": result.counts.created_slate_revision_count,
                        "offer_families": result.counts.created_offer_family_count,
                        "offer_revisions": result.counts.created_offer_revision_count,
                    },
                    "committed_counts": {
                        "slate_revisions": result.counts.slate_revision_count,
                        "offer_families": result.counts.offer_family_count,
                        "offer_revisions": result.counts.offer_revision_count,
                    },
                    "persisted_counts": {
                        "slate_revisions": int(slate_count or 0),
                        "offer_families": int(family_count or 0),
                        "offer_revisions": int(offer_count or 0),
                    },
                }
            )
        )
    except (OSError, json.JSONDecodeError, WorkflowOperationError, ValueError) as error:
        _fail(error)


@workflow_app.command("record-official-schedule-check")
def record_official_schedule_check(
    manifest: Path = _MANIFEST_OPTION,
    contract_version: str = _CONTRACT_VERSION_OPTION,
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    """Record an official schedule collection fact through a typed Action."""
    try:
        document, digest = _manifest_document(
            manifest,
            contract_version=contract_version,
            expected_version="official-schedule-check-v1",
        )
        parsed = OfficialScheduleCheckManifestV1.model_validate(document)
        kernel = _kernel(data_dir)
        outcome = kernel.sale_actions.record_official_schedule_check(
            RecordOfficialScheduleCheckRequest(
                manifest=parsed,
                actor_id="system:official-sale",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"official-schedule-check-v1:{digest}",
                requested_at=_now(),
            )
        )
        if not outcome.status.is_success:
            raise WorkflowOperationError(
                outcome.error_detail or outcome.error_code or "schedule check rejected"
            )
        with kernel.engine.connect() as connection:
            persisted_receipt_count = connection.scalar(
                select(func.count())
                .select_from(sos.official_schedule_check_receipts)
                .where(sos.official_schedule_check_receipts.c.action_id == outcome.action_id)
            )
        _cli.typer.echo(
            canonical_json(
                {
                    "contract_version": "official-schedule-check-v1",
                    "action_id": outcome.action_id,
                    "status": outcome.status.value,
                    "lane": parsed.lane,
                    "shanghai_check_date": parsed.shanghai_check_date.isoformat(),
                    "check_state": parsed.check_state,
                    "persisted_receipt_count": int(persisted_receipt_count or 0),
                }
            )
        )
    except (OSError, json.JSONDecodeError, WorkflowOperationError, ValueError) as error:
        _fail(error)


@workflow_app.command("ingest-evidence")
def ingest_evidence(
    manifest: Path = _MANIFEST_OPTION,
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    """Import one strict external evidence manifest through its typed Action."""
    try:
        document = json.loads(Path(manifest).expanduser().read_text("utf-8"))
        if not isinstance(document, dict):
            raise WorkflowOperationError("manifest root must be a JSON object")
        parsed = EvidenceIntakeManifestV1.model_validate(document)
        kernel = _kernel(data_dir)
        result = kernel.evidence_actions.ingest_operator_evidence_manifest(
            IngestOperatorEvidenceRequest(
                manifest=parsed,
                actor_id="system:operator-evidence",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"evidence-intake-v1:{parsed.manifest_sha256}",
                requested_at=_now(),
            )
        )
        receipt = result.receipt
        if not result.outcome.status.is_success or receipt is None:
            raise WorkflowOperationError(
                result.outcome.error_detail
                or result.outcome.error_code
                or "evidence manifest quarantined"
            )
        if (
            receipt.manifest_sha256 != parsed.manifest_sha256
            or receipt.committed_count != receipt.persisted_count
            or receipt.rejected_count
            or receipt.skipped_count
        ):
            raise WorkflowOperationError(
                "evidence committed and persisted counts differ"
            )
        _cli.typer.echo(
            canonical_json(
                {
                    "contract_version": parsed.schema_version,
                    "action_id": result.outcome.action_id,
                    "status": result.outcome.status.value,
                    "lane": parsed.lane,
                    "business_key": parsed.business_key,
                    "manifest_sha256": parsed.manifest_sha256,
                    "committed_count": receipt.committed_count,
                    "persisted_count": receipt.persisted_count,
                }
            )
        )
    except (OSError, json.JSONDecodeError, WorkflowOperationError, ValueError) as error:
        _fail(error)


@workflow_app.command("import-legacy-operator")
def import_legacy_operator(
    manifest: Path = _MANIFEST_OPTION,
    contract_version: str = _CONTRACT_VERSION_OPTION,
    data_dir: Path = _DATA_DIR_OPTION,
    imported_at: str | None = _cli.typer.Option(None, "--imported-at"),
) -> None:
    """Import one explicitly versioned legacy artifact as replay-only data."""
    try:
        at = datetime.fromisoformat(imported_at) if imported_at is not None else _now()
        kernel = _kernel(data_dir)
        result = LegacyOperatorImporter(
            artifact_ingest=kernel.artifact_ingest,
            workflow=kernel.workflow,
        ).import_path(
            manifest,
            contract_version=contract_version,
            imported_at=at,
        )
        _cli.typer.echo(canonical_json(result.model_dump(mode="json")))
        if isinstance(result, LegacyQuarantineReport):
            raise _cli.typer.Exit(code=1)
    except _cli.typer.Exit:
        raise
    except (OSError, json.JSONDecodeError, WorkflowOperationError, ValueError) as error:
        _fail(error)


@workflow_app.command("register-rx")
def register_rx(
    rx_file: Path = _RX_FILE_OPTION,
    issue: str = _cli.typer.Option(..., "--issue"),
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    """把 rx 的 predictions/已决 adjudications 批量注册进本体(幂等,未决跳过)。"""
    try:
        kernel = _kernel(data_dir)
        rx = json.loads(Path(rx_file).expanduser().read_text("utf-8"))
        now = _now()
        for req in map_rx_predictions(rx, issue):
            outcome = kernel.workflow.register_prediction(
                RegisterPredictionRequest(
                    **req,
                    actor_id="operator:jun",
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    requested_at=now,
                )
            )
            _cli.typer.echo(f"{req['idempotency_key']}: {outcome.status.value}")
        adjs, skipped = map_rx_adjudications(rx, issue)
        for req in adjs:
            outcome = kernel.workflow.record_adjudication(
                RecordAdjudicationRequest(
                    **req,
                    supersedes_adjudication_id=None,
                    actor_id="operator:jun",
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    requested_at=now,
                )
            )
            _cli.typer.echo(f"{req['idempotency_key']}: {outcome.status.value}")
        for line in skipped:
            _cli.typer.echo(f"跳过 {line}")
    except (OSError, json.JSONDecodeError, WorkflowOperationError, ValueError) as error:
        _fail(error)


@workflow_app.command("grade-prediction")
def grade_prediction(
    prediction_id: str = _cli.typer.Option(..., "--prediction-id"),
    outcome: str = _cli.typer.Option(..., "--outcome", help="hit|miss|na"),
    reason: str = _cli.typer.Option(..., "--reason"),
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    """判定一条预注册预测(判断在主循环,此处只记账)。"""
    try:
        kernel = _kernel(data_dir)
        result = kernel.workflow.grade_prediction(
            GradePredictionRequest(
                prediction_id=prediction_id,
                outcome=outcome,
                reason=reason,
                actor_id="operator:jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"grade:{prediction_id}",
                requested_at=_now(),
            )
        )
        _cli.typer.echo(f"{prediction_id}: {result.status.value}")
    except (WorkflowOperationError, ValueError) as error:
        _fail(error)
