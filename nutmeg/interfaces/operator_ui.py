"""Focused server-rendered operator task routes."""
from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.operator_contracts import OperatorLane
from nutmeg.product.operator_runtime import (
    OperatorRuntimeConfig,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
)

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
    *,
    mount_root: bool = True,
    mount_next: bool = False,
    read_only: bool = False,
) -> None:
    web_root = Path(__file__).resolve().parent / "web"
    templates = Jinja2Templates(directory=web_root / "templates")

    def workbench_context(**values):
        return {
            "workspace": "operator-workbench",
            "read_only": read_only,
            "today_href": "/" if mount_root and not read_only else "/operator-next",
            **values,
        }

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
                "read_only": read_only,
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

    async def operator_root(request: Request):
        try:
            worklist = services.operator_queries.worklist(as_of=clock())
            if worklist.selected is None:
                return templates.TemplateResponse(
                    request=request,
                    name="operator/tasks.html",
                    context={
                        "workspace": "operator-tasks",
                        "worklist": worklist,
                        "read_only": read_only,
                    },
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

    v2_at_root = mount_root and not read_only

    if mount_root and not v2_at_root:
        app.add_api_route(
            "/",
            operator_root,
            methods=["GET"],
            include_in_schema=False,
        )

    if mount_next or v2_at_root:
        today_path = "/" if v2_at_root else "/operator-next"

        async def operator_today_page(request: Request):
            try:
                today = services.operator_queries.today(as_of=clock())
                return templates.TemplateResponse(
                    request=request,
                    name="operator/today.html",
                    context=workbench_context(today=today),
                )
            except ProductNotFoundError:
                raise
            except Exception as error:
                return unexpected_response(request, error)

        app.add_api_route(
            today_path,
            operator_today_page,
            methods=["GET"],
            include_in_schema=False,
        )

        @app.get(
            "/operator-next/audit/{audit_token}",
            include_in_schema=False,
        )
        async def operator_audit_page(request: Request, audit_token: str):
            try:
                audit_envelope = services.operator_queries.audit(
                    audit_token,
                    as_of=clock(),
                )
                return templates.TemplateResponse(
                    request=request,
                    name="operator/_audit_details.html",
                    context=workbench_context(audit_envelope=audit_envelope),
                )
            except ProductNotFoundError:
                raise
            except Exception as error:
                return unexpected_response(request, error)

        @app.get("/operator-next/maintenance", include_in_schema=False)
        async def operator_maintenance_page(request: Request):
            try:
                maintenance = services.operator_queries.maintenance(as_of=clock())
                return templates.TemplateResponse(
                    request=request,
                    name="operator/maintenance.html",
                    context=workbench_context(maintenance=maintenance),
                )
            except ProductNotFoundError:
                raise
            except Exception as error:
                return unexpected_response(request, error)

        @app.get("/operator-next/{lane}", include_in_schema=False)
        async def operator_lane_page(request: Request, lane: OperatorLane):
            try:
                lane_view = services.operator_queries.lane(lane, as_of=clock())
                return templates.TemplateResponse(
                    request=request,
                    name="operator/lane.html",
                    context=workbench_context(lane_view=lane_view),
                )
            except ProductNotFoundError:
                raise
            except Exception as error:
                return unexpected_response(request, error)

        @app.get(
            "/operator-next/{lane}/{business_key}",
            include_in_schema=False,
        )
        async def operator_task_v2_page(
            request: Request,
            lane: OperatorLane,
            business_key: str,
        ):
            try:
                task_v2 = services.operator_queries.task_v2(
                    lane,
                    business_key,
                    as_of=clock(),
                )
                return templates.TemplateResponse(
                    request=request,
                    name="operator/task_v2.html",
                    context=workbench_context(task_v2=task_v2),
                )
            except ProductNotFoundError:
                raise
            except Exception as error:
                return unexpected_response(request, error)

        @app.get(
            "/operator-next/{lane}/{business_key}/{work_item_key}",
            include_in_schema=False,
        )
        async def operator_work_item_page(
            request: Request,
            lane: OperatorLane,
            business_key: str,
            work_item_key: str,
        ):
            try:
                task_v2 = services.operator_queries.work_item_v2(
                    lane,
                    business_key,
                    work_item_key,
                    as_of=clock(),
                )
                return templates.TemplateResponse(
                    request=request,
                    name="operator/work_item.html",
                    context=workbench_context(
                        task_v2=task_v2,
                        work_item=task_v2.active_work_item,
                    ),
                )
            except ProductNotFoundError:
                task_v2 = services.operator_queries.task_v2(
                    lane,
                    business_key,
                    as_of=clock(),
                )
                current_key = task_v2.active_work_item.work_item_key
                if current_key == work_item_key:
                    raise
                return RedirectResponse(
                    f"/operator-next/{lane.value}/{business_key}/{current_key}",
                    status_code=307,
                )
            except Exception as error:
                return unexpected_response(request, error)

    @app.get("/tasks", include_in_schema=False)
    async def operator_tasks_page(request: Request):
        try:
            worklist = services.operator_queries.worklist(as_of=clock())
            return templates.TemplateResponse(
                request=request,
                name="operator/tasks.html",
                context={
                    "workspace": "operator-tasks",
                    "worklist": worklist,
                    "read_only": read_only,
                },
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
                context={
                    "workspace": "operator-evidence",
                    "detail": detail,
                    "read_only": read_only,
                },
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
            context={"workspace": "system-maintenance", "read_only": read_only},
        )


def mount_operator_rollout_routes(
    app: FastAPI,
    runtime: OperatorRuntimeConfig,
) -> None:
    """Own `/` and `/operator-next` according to the closed rollout matrix."""
    if (
        runtime.runtime_scope is OperatorRuntimeScope.ISOLATED_CANDIDATE
        and runtime.surface_mode is OperatorSurfaceMode.ACTIVE
    ):

        @app.get("/", include_in_schema=False)
        async def isolated_root_redirect():
            return RedirectResponse("/operator-next", status_code=307)

    if runtime.surface_mode is OperatorSurfaceMode.LEGACY_READ_ONLY:
        return

    if (
        runtime.runtime_scope is OperatorRuntimeScope.PRODUCTION
        and runtime.surface_mode is OperatorSurfaceMode.ACTIVE
    ):

        @app.get("/operator-next", include_in_schema=False)
        async def production_next_redirect():
            return RedirectResponse("/", status_code=307)
