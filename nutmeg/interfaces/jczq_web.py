from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nutmeg.services.jczq_web import JczqWebCockpitService, JczqWebValidationError


def create_jczq_web_app(*, service: JczqWebCockpitService) -> FastAPI:
    app = FastAPI(title="Nutmeg JCZQ Cockpit")
    web_root = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")
    templates = Jinja2Templates(directory=web_root / "templates")

    @app.get("/jczq")
    def dashboard_page(request: Request):
        return templates.TemplateResponse(
            request,
            "jczq/dashboard.html",
            {"title": "JCZQ Cockpit", "dashboard": service.dashboard()},
        )

    @app.get("/jczq/api")
    def dashboard_api() -> dict[str, Any]:
        return service.dashboard()

    @app.get("/jczq/daily/{run_date}")
    def workspace_page(request: Request, run_date: str):
        return templates.TemplateResponse(
            request,
            "jczq/workspace.html",
            {"title": f"JCZQ {run_date}", "workspace": service.workspace(run_date)},
        )

    @app.get("/jczq/daily/{run_date}/api")
    def workspace_api(run_date: str) -> dict[str, Any]:
        return service.workspace(run_date)

    @app.post("/jczq/daily/{run_date}/brief")
    async def load_brief(request: Request, run_date: str):
        form = await _urlencoded_form(request)
        service.load_brief(run_date=run_date, brief_text=str(form.get("brief_text") or ""))
        return RedirectResponse(f"/jczq/daily/{run_date}", status_code=303)

    @app.post("/jczq/daily/{run_date}/debate/init")
    def initialize_debate(run_date: str):
        service.initialize_debate(run_date)
        return RedirectResponse(f"/jczq/daily/{run_date}", status_code=303)

    @app.post("/jczq/daily/{run_date}/analysis/{agent}")
    async def save_analysis(request: Request, run_date: str, agent: str):
        form = await _urlencoded_form(request)
        service.save_analysis(
            run_date=run_date,
            agent=agent,
            content=str(form.get("content") or ""),
        )
        return RedirectResponse(f"/jczq/daily/{run_date}", status_code=303)

    @app.post("/jczq/daily/{run_date}/debate/compare")
    def compare_debate(run_date: str):
        service.compare_debate(run_date)
        return RedirectResponse(f"/jczq/daily/{run_date}", status_code=303)

    @app.post("/jczq/daily/{run_date}/tickets/draft")
    async def draft_tickets(run_date: str, body: dict[str, Any]):
        try:
            return service.draft_ticket_version(
                run_date=run_date,
                source=str(body.get("source") or "human"),
                best_pick=body.get("best_pick"),
                tickets=list(body.get("tickets") or []),
            )
        except JczqWebValidationError as exc:
            return JSONResponse(
                {"error": "validation_failed", "findings": exc.findings},
                status_code=422,
            )

    @app.post("/jczq/daily/{run_date}/tickets/{version}/finalize")
    def finalize_tickets(run_date: str, version: int):
        try:
            service.finalize_version(run_date, version)
        except JczqWebValidationError as exc:
            return JSONResponse(
                {"error": "validation_failed", "findings": exc.findings},
                status_code=422,
            )
        return RedirectResponse(f"/jczq/daily/{run_date}", status_code=303)

    @app.post("/jczq/daily/{run_date}/reviews")
    async def record_review(run_date: str, body: dict[str, Any]):
        return service.record_review(
            run_date=run_date,
            version=int(body["version"]),
            ticket_id=str(body["ticket_id"]),
            status=str(body["status"]),
            actual_return=_optional_float(body.get("actual_return")),
            profit_loss=_optional_float(body.get("profit_loss")),
            failed_leg=body.get("failed_leg"),
            notes=body.get("notes"),
            leg_reviews=list(body.get("leg_reviews") or []),
        )

    return app


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


async def _urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode()
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}
