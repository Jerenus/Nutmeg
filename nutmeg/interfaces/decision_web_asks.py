"""行内追问的路由（2026-11-02 产品形态第 10 阶段 Task 10.4）。

页面上「问」→ `asks.ask` 记进当天讨论流 → 唤醒后台作答线程（`asks.work`，同一时刻只答一个）→
页面轮询 `/api/ask?obj=` 看到答行。给应答员的「这一行此刻显示什么」取自页面自己的接口
（issue_payload / jczq_payload / ledger_payload），不另推导。

测试替身：`app.state.ask_runner`（假 claude）、`app.state.ask_push`（假推送）、
`app.state.ask_background = False`（同步作答）。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def excerpt_for(data_dir: Path, obj: str, *, now) -> str:
    """对象所在页的那一行（或整页摘要）→ JSON 文本。"""
    head, _, rest = obj.partition(":")
    top, _, sub = rest.partition("/")
    sub = sub.split("/", 1)[0]
    if head == "issue":
        from nutmeg.interfaces.decision_web_issue import issue_payload

        p = issue_payload(data_dir, top, today=now.date())
        base = {k: p.get(k) for k in ("issue", "default", "main_shape", "signed_bold",
                                      "built_at", "errors")} | {"brake": p["brake"]}
        if sub.startswith("m"):
            row = next((m for m in p["matches"] if m["no"] == sub[1:]), None)
            corr = [c for c in p.get("corrections") or [] if c["obj"].startswith(f"{obj}")]
            return _dump(base | {"match": row, "corrections": corr})
        brief = [{k: v for k, v in m.items() if k != "matrix"} for m in p["matches"]]
        return _dump(base | {"matches": brief, "bridge": p.get("bridge"),
                             "draft_candidates": p.get("draft_candidates")})
    if head == "jczq":
        from nutmeg.interfaces.decision_web_jczq import jczq_payload

        p = jczq_payload(data_dir, top, now=now)
        if sub:
            return _dump({"day": top, "row": next((r for r in p["rows"] if r.get("code") == sub),
                                                  None)})
        return _dump({k: v for k, v in p.items()})
    if head == "ledger":
        from nutmeg.interfaces.decision_web_ledger import ledger_payload

        p = ledger_payload(data_dir, top, today=now.date())
        if sub:
            return _dump({"month": top, "report": p.get("report"),
                          "issue": next((i for i in p.get("issues") or []
                                         if str(i.get("issue")) == sub), None)})
        return _dump({k: p.get(k) for k in ("report", "issues", "jczq_days", "errors")})
    return "（这个对象没有页面数据）"


class _Worker:
    """一个后台线程：被唤醒就把待答问答完；已在跑时再唤醒只置一个标记，跑完再来一轮。"""

    def __init__(self, app: FastAPI):
        self.app = app
        self.busy: set = set()
        self._lock = threading.Lock()
        self._running = False
        self._again = False

    def _run_once(self) -> None:
        from nutmeg.decision import asks

        state = self.app.state
        now = state.now()
        asks.work(state.data_dir, today=now.date().isoformat(),
                  excerpt_for=lambda obj: excerpt_for(Path(state.data_dir), obj, now=state.now()),
                  runner=getattr(state, "ask_runner", None),
                  push=getattr(state, "ask_push", asks.telegram_push), busy=self.busy)

    def _loop(self) -> None:
        import logging

        while True:
            try:
                self._run_once()
            except Exception:  # noqa: BLE001 — 线程不能静默死掉留个「在跑」标记
                logging.getLogger(__name__).exception("应答员一轮失败")
            with self._lock:
                if not self._again:
                    self._running = False
                    return
                self._again = False

    def kick(self) -> None:
        if not getattr(self.app.state, "ask_background", True):
            self._run_once()
            return
        with self._lock:
            if self._running:
                self._again = True
                return
            self._running = True
        threading.Thread(target=self._loop, name="nutmeg-asker", daemon=True).start()

    @property
    def running(self) -> bool:
        return self._running


def register_ask_routes(app: FastAPI) -> None:
    worker = _Worker(app)
    app.state.ask_worker = worker

    @app.get("/api/ask")
    def ask_thread(obj: str) -> Any:
        from nutmeg.decision import asks

        try:
            obj = asks.check_obj(obj)
        except ValueError as error:
            return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
        today = app.state.now().date().isoformat()
        rows = asks.thread(app.state.data_dir, obj, today=today)
        # 重启丢了后台线程、问还挂着 → 有人来看就接着答（只答最近两天的）
        if not worker.running and any(r["answer"] is None for r in rows) and \
                asks.pending(app.state.data_dir, today=today):
            worker.kick()
        busy = [f"{d}#{s}" for d, s in sorted(worker.busy)]
        return {"obj": obj, "page": asks.page_path(obj), "thread": _with_drafts(rows),
                "busy": busy, "quick": list(asks.QUICK)}

    def _with_drafts(rows: list[dict]) -> list[dict]:
        """答行里的纠正 id → 账上此刻的样子（旧/新/状态），页面就地确认用。"""
        from nutmeg.decision.corrections import load

        wanted = {c for r in rows for c in ((r["answer"] or {}).get("corrections") or [])}
        if not wanted:
            return rows
        keys = ("id", "obj", "old", "new", "status")
        by_id = {c["id"]: {k: c.get(k) for k in keys} for c in load(app.state.data_dir)
                 if c["id"] in wanted}
        return [r if not (r["answer"] or {}).get("corrections") else
                {**r, "answer": {**r["answer"], "correction_rows":
                                 [by_id[c] for c in r["answer"]["corrections"] if c in by_id]}}
                for r in rows]

    @app.post("/action/ask")
    def ask_post(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision import asks

        try:
            at = app.state.now()
            got = asks.ask(app.state.data_dir, obj=str(payload.get("obj") or ""),
                           text=str(payload.get("text") or ""),
                           at=at if at.tzinfo else None)
        except ValueError as error:
            return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
        worker.kick()
        return {"ok": True, **got}
