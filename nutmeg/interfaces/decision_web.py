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


def _factor_cls():
    from nutmeg.decision.ontology import Factor
    return Factor


def self_daily(output_dir, date: str) -> Path:
    return Path(output_dir) / "daily" / date


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

    from datetime import date as _date

    from fastapi import Body
    from fastapi.responses import JSONResponse

    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.read_ingest import ingest_reads
    from nutmeg.decision.workbench import distill_note, record_decision

    def _today() -> str:
        return _date.today().isoformat()

    def _date_of(match_id: str) -> str:
        # M-<date>-... → date(供 record_decision 归日)
        parts = match_id.split("-")
        return "-".join(parts[1:4]) if len(parts) >= 4 else _today()

    @app.post("/action/approve-read")
    def approve_read(payload: dict = Body(...)) -> Any:  # noqa: B008
        read = dict(payload["read"])
        obj_id = payload.get("obj_id", read.get("read_id", ""))
        date = _date_of(read.get("match_id", ""))
        # §3.5:把该 obj 的追问往来蒸馏进 note(不进 store);判断不在此
        note = distill_note(output_dir, date, obj_id=obj_id)
        if note:
            read["note"] = (read.get("note", "") + " ⟨" + note + "⟩").strip()
        factors = store.load(_factor_cls()) or load_seed_factors()
        errors = ingest_reads([read], store=store, factors=factors)  # 同一校验闸
        if errors:
            record_decision(output_dir, date, action="approve_read",
                            obj_id=obj_id, result="拒绝: " + "; ".join(errors))
            return JSONResponse({"ok": False, "errors": errors}, status_code=400)
        record_decision(output_dir, date, action="approve_read",
                        obj_id=obj_id, result=f"{read['read_id']} 入库")
        return {"ok": True, "read_id": read["read_id"]}

    @app.post("/action/reject-read")
    def reject_read(payload: dict = Body(...)) -> Any:  # noqa: B008
        obj_id = payload.get("obj_id", "")
        date = payload.get("date", _today())
        record_decision(output_dir, date, action="reject_read", obj_id=obj_id,
                        result=payload.get("reason", ""))
        return {"ok": True}

    @app.post("/action/confirm-legs")
    def confirm_legs(payload: dict = Body(...)) -> Any:  # noqa: B008
        import json
        date = payload.get("date", _today())
        legs = payload["legs"]
        legs_file = self_daily(output_dir, date) / "legs.json"
        legs_file.parent.mkdir(parents=True, exist_ok=True)
        if legs_file.exists():        # 写前留 .bak(spec §5 幂等)
            legs_file.with_suffix(".json.bak").write_text(
                legs_file.read_text(encoding="utf-8"), encoding="utf-8")
        legs_file.write_text(json.dumps(legs, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        record_decision(output_dir, date, action="confirm_legs",
                        obj_id="legs", result=f"{len(legs)} 腿 → legs.json")
        return {"ok": True, "legs": len(legs)}

    from nutmeg.decision.workbench import append_user_message, read_events

    @app.post("/thread")
    def thread_post(payload: dict = Body(...)) -> Any:  # noqa: B008
        """§3.5:浏览器追问 → user_message 事件(obj_id 锚定)。终端 agent 监视
        文件后回应(写 agent_reply/read_draft),浏览器经 /events 拉回。"""
        date = payload.get("date", _today())
        append_user_message(output_dir, date, obj_id=payload["obj_id"],
                            text=payload["text"], at=payload.get("at", ""))
        return {"ok": True}

    @app.get("/events")
    def events(date: str, since: int = 0) -> dict:
        """轮询式事件拉取(SSE 的 HTTP 后备;前端 app.js 用 EventSource 或轮询)。
        返回 since 之后的新事件与新游标。"""
        evs = read_events(output_dir, date, since=since)
        cursor = evs[-1]["seq"] if evs else since
        return {"events": evs, "cursor": cursor}

    return app
