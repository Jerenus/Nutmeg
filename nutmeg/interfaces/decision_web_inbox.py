"""待签收件箱页的路由（2026-10-30 产品形态第 10 阶段 Task 10.3）。只读组装 + 一种答复。

数全来自 `proposals.inbox / summary / labels`（账 + 闭环里开着的 RSI 项）；页面只做答复：
签 / 改 / 否 / 已过时，带 Jun 的原话（改必填），by=jun。
「已执行」只由 CLI `nutmeg inbox done` 在真执行之后标。
读账失败只进 `errors`，接口不 500。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse


def inbox_payload(data_dir: Path | str) -> dict:
    """{rows, summary, labels, errors}。"""
    from nutmeg.decision.proposals import inbox, labels, summary

    errors: list[str] = []
    try:
        rows = inbox(data_dir)
    except Exception as exc:  # noqa: BLE001 —— 账读不出要看得见，不能读成「没有待签」
        rows = []
        errors.append(f"收件箱读取失败：{exc!r}"[:200])
    return {"rows": rows, "summary": summary(rows), "labels": labels(), "errors": errors}


def register_inbox_routes(app: FastAPI, templates) -> None:
    @app.get("/inbox")
    def inbox_page(request: Request):
        return templates.TemplateResponse(request, "decision/inbox.html", {"title": "待签"})

    @app.get("/api/inbox")
    def inbox_api() -> dict:
        return inbox_payload(app.state.data_dir)

    @app.post("/action/inbox/{pid}/answer")
    def inbox_answer(pid: str, payload: dict = Body(...)) -> Any:  # noqa: B008
        """页面上的答复：追加一条 answer 事件（by=jun）。"""
        from nutmeg.decision.proposals import answer

        try:
            (event,) = answer(app.state.data_dir, pid, str(payload.get("verdict") or ""),
                              words=str(payload.get("words") or ""), by="jun")
        except KeyError:
            return JSONResponse({"ok": False, "error": f"收件箱里没有 {pid}"}, status_code=404)
        except ValueError as error:
            return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
        return {"ok": True, "event": event}
