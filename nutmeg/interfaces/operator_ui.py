"""Focused server-rendered operator task routes."""
from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from nutmeg.product.errors import ProductNotFoundError

_LOGGER = logging.getLogger(__name__)

_DEPLOYMENT_LABELS = {
    "keep": "保留当前结构",
    "drop_match": "丢场式减注",
    "change_structure": "调整结构后重审",
    "empty_position": "空仓（当前部署门允许）",
}
_AUDIT_LABELS = {"pass": "PASS", "warn": "WARN", "error": "ERROR"}


def mount_operator_ui(
    app: FastAPI,
    services,
    clock: Callable[[], datetime],
) -> None:
    web_root = Path(__file__).resolve().parent / "web"
    templates = Jinja2Templates(directory=web_root / "templates")

    def task_response(request: Request, task):
        token_bytes = bytes.fromhex(task.mutation_token)
        return templates.TemplateResponse(
            request=request,
            name="operator/task.html",
            context={
                "workspace": "operator-task",
                "task": task,
                "deployment_labels": _DEPLOYMENT_LABELS,
                "audit_labels": _AUDIT_LABELS,
                "snapshot_token": base64.urlsafe_b64encode(token_bytes)
                .decode("ascii")
                .rstrip("="),
            },
        )

    def unexpected_response(request: Request, error: Exception):
        correlation_id = f"err-{uuid4().hex}"
        _LOGGER.exception(
            "operator UI request failed correlation_id=%s",
            correlation_id,
            exc_info=error,
        )
        return templates.TemplateResponse(
            request=request,
            name="operator/error.html",
            context={
                "workspace": "operator-error",
                "correlation_id": correlation_id,
            },
            status_code=500,
        )

    @app.get("/", include_in_schema=False)
    async def operator_root(request: Request):
        try:
            worklist = services.operator_queries.worklist(as_of=clock())
            if worklist.selected is None:
                return templates.TemplateResponse(
                    request=request,
                    name="operator/tasks.html",
                    context={"workspace": "operator-tasks", "worklist": worklist},
                )
            task = services.operator_queries.task(
                worklist.selected.task_id,
                as_of=worklist.as_of,
            )
            return task_response(request, task)
        except ProductNotFoundError:
            raise
        except Exception as error:
            return unexpected_response(request, error)

    @app.get("/tasks", include_in_schema=False)
    async def operator_tasks_page(request: Request):
        try:
            worklist = services.operator_queries.worklist(as_of=clock())
            return templates.TemplateResponse(
                request=request,
                name="operator/tasks.html",
                context={"workspace": "operator-tasks", "worklist": worklist},
            )
        except ProductNotFoundError:
            raise
        except Exception as error:
            return unexpected_response(request, error)

    @app.get(
        "/tasks/{task_id}/evidence/{evidence_key}",
        include_in_schema=False,
    )
    async def operator_evidence_page(
        request: Request,
        task_id: str,
        evidence_key: str,
    ):
        try:
            detail = services.operator_queries.evidence(
                task_id,
                evidence_key,
                as_of=clock(),
            )
            return templates.TemplateResponse(
                request=request,
                name="operator/evidence.html",
                context={"workspace": "operator-evidence", "detail": detail},
            )
        except ProductNotFoundError:
            raise
        except Exception as error:
            return unexpected_response(request, error)

    @app.get("/tasks/{task_id}", include_in_schema=False)
    async def operator_task_page(request: Request, task_id: str):
        try:
            return task_response(
                request,
                services.operator_queries.task(task_id, as_of=clock()),
            )
        except ProductNotFoundError:
            raise
        except Exception as error:
            return unexpected_response(request, error)

    @app.get("/system", include_in_schema=False)
    async def system_index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="operator/system.html",
            context={"workspace": "system-maintenance"},
        )
