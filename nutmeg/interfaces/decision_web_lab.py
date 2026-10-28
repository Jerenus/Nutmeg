"""实验室页的路由（2026-10-28 产品形态第 8 阶段 Task 8.1）。只读组装，不产生判断。

实验看板＝`lab.lab_board`（实证标签与 `rsi columns` 同一实现），研究层消费量＝`bridge.cite_totals`，
运维一行＝`day_ops.launchd_rows`（作业数 / 告警）与 `ops_run.failed_segments`（今天 runs.jsonl
里 exit≠0 的段，与 `nutmeg status` 同一份读法）。规则 v3 回放（gym 5.8 s）不在这页，留在
`nutmeg account month`。每块各自 try，失败只进 `errors`，接口不 500。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date as _date
from pathlib import Path

from fastapi import FastAPI, Request

from nutmeg.interfaces.decision_web_ledger import _block
from nutmeg.interfaces.decision_web_shell import _bj_date, app_now

# 与 CLI `rsi … --registry-dir` 的默认同一目录（CLI 默认是相对仓根的 experiments/registry）
REGISTRY_DIR = Path(__file__).resolve().parents[2] / "experiments" / "registry"


def _ops(data_dir: Path, launchd: Callable[[], list[dict]], today: _date) -> dict:
    """{jobs, alarms:[label], failed_runs}。"""
    from nutmeg.decision.ops_run import failed_segments

    rows = launchd()
    failed = failed_segments(data_dir, day=today.isoformat())
    return {"jobs": len(rows), "alarms": [r["label"] for r in rows if r.get("alarm")],
            "failed_runs": sum(len(v) for v in failed.values())}


def lab_payload(data_dir: Path | str, registry_dir: Path | str, *,
                launchd: Callable[[], list[dict]], today: _date) -> dict:
    """{board:{live, settled}, cites:{issues, diffs, matrix, outside, blank}|None,
    ops:{jobs, alarms, failed_runs}|None, errors}。`launchd` 是零参函数，现读 launchd 行。"""
    from nutmeg.decision.bridge import cite_totals
    from nutmeg.decision.lab import lab_board

    data_dir = Path(data_dir)
    errors: list[str] = []
    board = _block(errors, "实验看板", lambda: lab_board(data_dir, registry_dir),
                   {"live": [], "settled": [], "errors": []})
    errors += board.pop("errors", [])
    return {
        "board": board,
        "cites": _block(errors, "研究层消费量", lambda: cite_totals(data_dir), None),
        "ops": _block(errors, "运维", lambda: _ops(data_dir, launchd, today), None),
        "errors": errors,
    }


def register_lab_routes(app: FastAPI, templates) -> None:
    def _payload() -> dict:
        from nutmeg.decision.day_ops import launchd_rows

        data_dir = Path(app.state.data_dir)
        today = _date.fromisoformat(_bj_date(app_now(app)))
        registry = getattr(app.state, "lab_registry", None) or REGISTRY_DIR
        return lab_payload(
            data_dir, registry, today=today,
            launchd=lambda: launchd_rows(plists_dir=app.state.runs_plists,
                                         logs_dir=data_dir / "logs",
                                         launchctl_text=app.state.launchctl(), today=today))

    @app.get("/lab")
    def lab_page(request: Request):
        return templates.TemplateResponse(request, "decision/lab.html", {"title": "实验室"})

    @app.get("/api/lab")
    def lab_api() -> dict:
        return _payload()
