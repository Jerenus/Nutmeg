"""Strict, closed HTTP boundary for the v2 operator workbench."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.product.contracts import ProductError
from nutmeg.product.operator_contracts import OperatorCommandReceipt
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenError,
)


class OperatorCommandV2(BaseModel):
    """Base envelope used until each named business command is installed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2"]
    kind: OperatorCommandKind
    expected_snapshot_token: str = Field(min_length=1, max_length=8192)
    idempotency_key: str = Field(min_length=1, max_length=500)


class FreezeEvidenceCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.FREEZE_EVIDENCE]
    task_key: str = Field(pattern=r"^(?:jczq:\d{4}-\d{2}-\d{2}|zucai:\d{5})$")
    requirement_revision_token: str = Field(min_length=1, max_length=8192)


class RebuildScoreboardProjectionCommandV2(OperatorCommandV2):
    kind: Literal[OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION]


class UnavailableOperatorCommandV2(OperatorCommandV2):
    kind: Literal[
        OperatorCommandKind.RECORD_BASELINE_ENVELOPE,
        OperatorCommandKind.COMMIT_MATCH_JUDGMENT,
        OperatorCommandKind.FREEZE_JUDGMENT_PRESCRIPTION,
        OperatorCommandKind.REQUEST_CANDIDATE_GENERATION,
        OperatorCommandKind.SELECT_CANDIDATE,
        OperatorCommandKind.RECORD_NO_TICKET,
        OperatorCommandKind.SUPERSEDE_NO_TICKET,
        OperatorCommandKind.CREATE_TICKET_BATCH,
        OperatorCommandKind.ADJUDICATE_AUDIT_WARN,
        OperatorCommandKind.APPROVE_TICKET_BATCH,
        OperatorCommandKind.REQUEST_CONFIRMATION,
        OperatorCommandKind.REQUEST_SETTLEMENT,
        OperatorCommandKind.GRADE_PREDICTION,
        OperatorCommandKind.RECORD_SCOREBOARD_EFFECT_DISPOSITION,
        OperatorCommandKind.RECORD_SCOREBOARD_OBSERVATION,
        OperatorCommandKind.REQUEST_SCOREBOARD_REVIEW_COMPLETION,
    ]


InstalledOperatorCommandV2 = Annotated[
    FreezeEvidenceCommandV2
    | RebuildScoreboardProjectionCommandV2
    | UnavailableOperatorCommandV2,
    Field(discriminator="kind"),
]


def mount_operator_api(
    app: FastAPI,
    *,
    require_mutation_session: Callable[[Request], Awaitable[None]],
    operator_actions=None,
    actor_id: str | None = None,
) -> None:
    """Mount the sole v2 mutation path without a generic execution fallback."""

    if operator_actions is None:
        @app.post("/api/v2/operator")
        async def unavailable_operator_command(
            request: Request,
            command: OperatorCommandV2,
        ) -> JSONResponse:
            await require_mutation_session(request)
            error = ProductError(
                code="command_unavailable",
                message=f"operator command {command.kind.value} is not installed",
                retryable=False,
            )
            return JSONResponse(status_code=409, content=error.model_dump(mode="json"))

        return

    if actor_id is None or not actor_id.strip():
        raise ValueError("operator API requires one server-owned actor")

    @app.post("/api/v2/operator")
    async def operator_command(
        request: Request,
        command: InstalledOperatorCommandV2,
    ) -> JSONResponse:
        await require_mutation_session(request)
        try:
            if isinstance(command, FreezeEvidenceCommandV2):
                result = operator_actions.request_evidence_freeze(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 202
            elif isinstance(command, RebuildScoreboardProjectionCommandV2):
                result = operator_actions.rebuild_scoreboard_projection(
                    command,
                    actor_id=actor_id,
                    actor_role=ActorRole.JUDGE_OPERATOR,
                )
                status_code = 200
            else:
                error = ProductError(
                    code="command_unavailable",
                    message=f"operator command {command.kind.value} is not installed",
                    retryable=False,
                )
                return JSONResponse(
                    status_code=409,
                    content=error.model_dump(mode="json"),
                )
        except OperatorSnapshotTokenError as error:
            product_error = ProductError(
                code=error.code,
                message=str(error),
                retryable=False,
                details=(
                    {"recovery_href": "/operator-next"}
                    if error.code == "task_snapshot_changed"
                    else {}
                ),
            )
            return JSONResponse(
                status_code=409 if error.code == "task_snapshot_changed" else 422,
                content=product_error.model_dump(mode="json"),
            )
        receipt = OperatorCommandReceipt.model_validate(result)
        return JSONResponse(
            status_code=status_code,
            content=receipt.model_dump(mode="json"),
        )


__all__ = [
    "FreezeEvidenceCommandV2",
    "InstalledOperatorCommandV2",
    "OperatorCommandV2",
    "RebuildScoreboardProjectionCommandV2",
    "mount_operator_api",
]
