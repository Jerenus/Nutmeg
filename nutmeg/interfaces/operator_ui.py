"""Focused server-rendered operator task routes."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates


def mount_operator_ui(
    app: FastAPI,
    services,
    clock: Callable[[], datetime],
) -> None:
    web_root = Path(__file__).resolve().parent / "web"
    templates = Jinja2Templates(directory=web_root / "templates")

    def task_response(request: Request, task):
        return templates.TemplateResponse(
            request=request,
            name="operator/task.html",
            context={
                "workspace": "operator-task",
                "task": task,
            },
        )

    @app.get("/", include_in_schema=False)
    async def operator_root(request: Request):
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

    @app.get("/tasks", include_in_schema=False)
    async def operator_tasks_page(request: Request):
        worklist = services.operator_queries.worklist(as_of=clock())
        return templates.TemplateResponse(
            request=request,
            name="operator/tasks.html",
            context={"workspace": "operator-tasks", "worklist": worklist},
        )

    @app.get("/tasks/{task_id}", include_in_schema=False)
    async def operator_task_page(request: Request, task_id: str):
        return task_response(
            request,
            services.operator_queries.task(task_id, as_of=clock()),
        )

    @app.get("/system", include_in_schema=False)
    async def system_index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="operator/system.html",
            context={"workspace": "system-maintenance"},
        )
