"""Workshop UI — 决策本体判读工作台(spec 2026-07-07-workshop-ui-design.md)。

独立 FastAPI 应用,直接读 DecisionStore 九对象。判断永不在此:界面只渲染
agent 判断(workbench 事件)+ 记录人裁决。两个 typed action(Task 4)复用
ingest_reads/compose_tickets 的既有校验,零旁门。仿 client_web.py 模式。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nutmeg.decision.ontology import MarketSnapshot, Match
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.workbench import read_events


def _day_state(store: DecisionStore, output_dir, date: str) -> dict[str, Any]:
    prefix = f"M-{date}-"
    matches = [m.to_dict() for m in store.load(Match)
               if m.match_id.startswith(prefix)]
    snaps = [s.to_dict() for s in store.load(MarketSnapshot)
             if s.match_id.startswith(prefix) and s.kind == "read_time"]
    return {
        "date": date,
        "matches": matches,
        "snapshots": snaps,
        "events": read_events(output_dir, date),
    }


def create_decision_app(*, store: DecisionStore, output_dir) -> FastAPI:
    app = FastAPI(title="Nutmeg 判读工作台")
    web_root = Path(__file__).parent / "web"
    templates = Jinja2Templates(directory=web_root / "templates")
    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")
    app.state.store = store
    app.state.output_dir = Path(output_dir)

    @app.get("/api/workbench")
    def workbench_api(date: str) -> dict:
        return _day_state(store, output_dir, date)

    @app.get("/")
    def workbench_page(request: Request, date: str = ""):
        from datetime import date as _d
        date = date or _d.today().isoformat()
        return templates.TemplateResponse(
            request, "decision/workbench.html",
            {"title": "判读工作台", "state": _day_state(store, output_dir, date)})

    return app
