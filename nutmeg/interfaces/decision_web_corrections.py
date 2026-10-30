"""纠正账页的路由（2026-10-30 产品形态第 10 阶段 Task 10.2）。只读组装 + 两种状态改动。

数全来自 `corrections.load / summary / labels`；类型筛选在页面里做（只是显示过滤），堆计数、草稿数
由服务端给。页面只许把草稿改成「已确认·待回写」或「不改·记一笔」——「已回写」「无处可写」要在
真回写之后由 CLI `nutmeg correction status` 标。读账失败只进 `errors`，接口不 500。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

PAGE_STATUSES = ("confirmed", "dismissed")


def corrections_payload(data_dir: Path | str, *, obj: str = "", kind: str = "",
                        status: str = "") -> dict:
    """{rows, summary, labels, errors}。`summary` 按全账算（筛选不改堆与草稿数）。"""
    from nutmeg.decision.corrections import for_obj, labels, load, summary

    errors: list[str] = []
    try:
        rows = load(data_dir)
    except Exception as exc:  # noqa: BLE001 —— 账读不出要看得见，不能读成「没有纠正」
        rows = []
        errors.append(f"纠正账读取失败：{exc!r}"[:200])
    total = summary(rows)
    if obj:
        rows = for_obj(rows, obj)
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return {"rows": rows, "summary": total, "labels": labels(), "errors": errors}


def register_corrections_routes(app: FastAPI, templates) -> None:
    @app.get("/corrections")
    def corrections_page(request: Request):
        return templates.TemplateResponse(request, "decision/corrections.html", {"title": "纠正账"})

    @app.get("/api/corrections")
    def corrections_api(obj: str = "", kind: str = "", status: str = "") -> dict:
        return corrections_payload(app.state.data_dir, obj=obj, kind=kind, status=status)

    @app.post("/action/correction/{cid}/status")
    def correction_status(cid: str, payload: dict = Body(...)) -> Any:  # noqa: B008
        """页面上的「确认」/「不改·记一笔」：追加一条状态事件（by=jun）。"""
        from nutmeg.decision.corrections import STATUSES, set_status

        status = str(payload.get("status") or "")
        if status not in PAGE_STATUSES:
            allowed = " / ".join(STATUSES[s] for s in PAGE_STATUSES)
            return JSONResponse({"ok": False, "error": f"页面上只能改成 {allowed}"},
                                status_code=400)
        try:
            event = set_status(app.state.data_dir, cid, status,
                               note=str(payload.get("note") or "").strip())
        except KeyError:
            return JSONResponse({"ok": False, "error": f"账上没有 {cid}"}, status_code=404)
        return {"ok": True, "event": event}
