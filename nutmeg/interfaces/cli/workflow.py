"""Workflow object ingestion: rx 散文 → typed Actions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.config.settings import AppSettings
from nutmeg.decision.rx_ingest import map_rx_adjudications, map_rx_predictions
from nutmeg.ontology.actions.models import ActorRole, canonical_json
from nutmeg.ontology.actions.workflow_actions import (
    GradePredictionRequest,
    RecordAdjudicationRequest,
    RegisterPredictionRequest,
)
from nutmeg.ontology.errors import IdempotencyConflictError

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
        for mapped in map_rx_predictions(rx, issue):
            req = dict(mapped)
            alias_ids = req.pop("alias_ids")
            outcome = kernel.workflow.register_prediction(
                RegisterPredictionRequest(
                    **req,
                    actor_id="operator:jun",
                    actor_role=ActorRole.JUDGE_OPERATOR,
                    requested_at=now,
                )
            )
            aliases = f" aliases={','.join(alias_ids)}" if len(alias_ids) > 1 else ""
            _cli.typer.echo(
                f"{req['idempotency_key']}: {outcome.status.value}{aliases}"
            )
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


@workflow_app.command("grade-rx")
def grade_rx(
    rx_file: Path = _RX_FILE_OPTION,
    issue: str = _cli.typer.Option(..., "--issue"),
    data_dir: Path = _DATA_DIR_OPTION,
) -> None:
    """按 rx 的 `outcome` 字段批量判定预测（P1..Pn → prediction-<hex> 自动对号）。

    判断仍在主循环：本命令只读 rx 里**已经写好**的 outcome，不推断任何一条的结果。
    """
    from nutmeg.decision.rx_ingest import map_rx_gradings
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    try:
        kernel = _kernel(data_dir)
        rx = json.loads(Path(rx_file).expanduser().read_text("utf-8"))
        gradings, skipped = map_rx_gradings(rx, issue)
        now = _now()
        for g in gradings:
            with OntologyUnitOfWork(kernel.engine) as uow:
                action = uow.actions.get_by_idempotency_key(g["idempotency_key"])
            ref = next((r for r in (action.result_refs if action else ())
                        if r.object_type == "prediction"), None)
            if ref is None:
                _cli.typer.echo(f"{g['rx_id']}: 未注册（先跑 register-rx）")
                continue
            try:
                result = kernel.workflow.grade_prediction(
                    GradePredictionRequest(
                        prediction_id=ref.object_id, outcome=g["outcome"],
                        reason=g["reason"], actor_id="operator:jun",
                        actor_role=ActorRole.JUDGE_OPERATOR,
                        idempotency_key=f"grade:{ref.object_id}",
                        requested_at=now,
                    )
                )
            except IdempotencyConflictError:
                # 已判定过且理由不同 —— 判定是一次性的，不能被批量重跑悄悄改写。
                _cli.typer.echo(f"{g['rx_id']}: 已判定（理由不同，未覆盖）")
                continue
            _cli.typer.echo(f"{g['rx_id']} → {g['outcome']}: {result.status.value}")
        for line in skipped:
            _cli.typer.echo(f"跳过 {line}")
    except (WorkflowOperationError, ValueError) as error:
        _fail(error)
