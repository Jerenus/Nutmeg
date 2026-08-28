"""Workflow object ingestion: rx 散文 → typed Actions."""
from __future__ import annotations

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

workflow_app = _cli.typer.Typer(help="rx 对象化与预测判定")
_cli.app.add_typer(workflow_app, name="workflow")

_DATA_DIR_OPTION = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_RX_FILE_OPTION = _cli.typer.Option(..., "--rx-file")


class WorkflowOperationError(RuntimeError):
    """Raised when a workflow CLI operation cannot proceed."""


def _kernel(data_dir: Path):
    resolved = Path(data_dir).expanduser().resolve()
    kernel = _cli.build_ontology_kernel(AppSettings(data_dir=resolved))
    status = kernel.status()
    if not status.initialized or status.integrity_check != "ok" or status.pending_migrations:
        raise WorkflowOperationError(
            "ontology must be initialized, healthy, and current"
        )
    return kernel


def _fail(error: Exception) -> None:
    _cli.typer.echo(
        canonical_json({"code": "workflow_operation_blocked", "message": str(error)})
    )
    raise _cli.typer.Exit(code=1)


def _now() -> datetime:
    return datetime.now(UTC)


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
