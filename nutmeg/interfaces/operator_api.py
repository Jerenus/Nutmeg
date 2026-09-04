"""Strict, closed HTTP boundary for the v2 operator workbench."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from nutmeg.product.contracts import ProductError
from nutmeg.product.operator_tokens import OperatorCommandKind


class OperatorCommandV2(BaseModel):
    """Base envelope used until each named business command is installed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2"]
    kind: OperatorCommandKind
    expected_snapshot_token: str = Field(min_length=1, max_length=8192)
    idempotency_key: str = Field(min_length=1, max_length=500)


def mount_operator_api(
    app: FastAPI,
    *,
    require_mutation_session: Callable[[Request], Awaitable[None]],
) -> None:
    """Mount the sole v2 mutation path without a generic execution fallback."""

    @app.post("/api/v2/operator")
    async def operator_command(
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


__all__ = ["OperatorCommandV2", "mount_operator_api"]
