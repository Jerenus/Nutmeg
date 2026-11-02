"""票据收件的路由（2026-11-02 产品形态第 10 阶段 Task 10.5）。

期页「传截图」→ `POST /api/issue/{期}/intake`（data URL）存原图、起一个线程 `intake.read_ticket`
看图读格 → 页面轮询 `GET /api/issue/{期}/intake/{id}` 拿读数，填进决策表；对账（截图底部 vs 抄录卡）
在 `slip500` 带 `intake` 时由服务端算，登记仍走 `/action/issue/{期}/register`（带 `intake` 时对不上
就不收）。原图 `GET /intake/{期}/{id}` 供页面对照看。

测试替身：`app.state.intake_runner`、`app.state.intake_background = False`。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse


def register_intake_routes(app: FastAPI) -> None:
    from nutmeg.interfaces.decision_web_issue import _check_issue, _matrices, _names

    reading: set[tuple[str, str]] = set()

    def _read(issue: str, iid: str) -> None:
        from nutmeg.decision.intake import read_ticket

        data_dir = Path(app.state.data_dir)
        try:
            read_ticket(data_dir, issue, iid, names=_names(data_dir, issue,
                                                           _matrices(data_dir, issue, [])),
                        runner=getattr(app.state, "intake_runner", None))
        finally:
            reading.discard((issue, iid))

    @app.post("/api/issue/{issue}/intake")
    def intake_post(issue: str, payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.intake import decode_data_url, save_image

        _check_issue(issue)
        try:
            raw, ext = decode_data_url(str(payload.get("image") or ""))
            iid = save_image(app.state.data_dir, issue, raw, ext)
        except ValueError as error:
            return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
        reading.add((issue, iid))
        if getattr(app.state, "intake_background", True):
            threading.Thread(target=_read, args=(issue, iid), name="nutmeg-intake",
                             daemon=True).start()
        else:
            _read(issue, iid)
        return {"ok": True, "id": iid}

    @app.get("/api/issue/{issue}/intake/{iid}")
    def intake_get(issue: str, iid: str) -> Any:
        from nutmeg.decision.intake import image_path, load_result

        _check_issue(issue)
        if image_path(app.state.data_dir, issue, iid) is None:
            return JSONResponse({"ok": False, "error": f"没有收件 {iid}"}, status_code=404)
        done = load_result(app.state.data_dir, issue, iid)
        if done is not None:
            return {"ok": True, **done, "image_url": f"/intake/{issue}/{iid}"}
        url = f"/intake/{issue}/{iid}"
        if (issue, iid) in reading:
            return {"ok": True, "id": iid, "state": "reading", "image_url": url}
        return {"ok": True, "id": iid, "state": "failed", "image_url": url,
                "error": "读图中断（服务重启过），再传一次"}

    @app.get("/intake/{issue}/{iid}")
    def intake_image(issue: str, iid: str):
        from nutmeg.decision.intake import image_path

        path = image_path(app.state.data_dir, _check_issue(issue), iid)
        if path is None:
            raise HTTPException(status_code=404)
        return FileResponse(path)
