"""版图快照（2026-11-13，版图第 2 版拓展 6）：结构数字一条命令出齐。**只读。**

系统版图页的数字原先靠手工逐项核查，八天就落后一版。这里把同一组数字收成一份 JSON：
代码规模、内核表、作业定义与装载、近几天各作业成败、实验状态、待签积压。
只数结构，不带票面、资金与账号——快照可以直接进对外的结构页。
每一块独立取数：某块读不出只在该块留 `_error`，其余照出。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

_ROUTE = re.compile(r"^\s*@\w+\.(?:get|post|put|delete|patch)\(", re.M)
_TEST = re.compile(r"^\s*(?:async\s+)?def test_", re.M)


def code_stats(root: Path | str) -> dict:
    root = Path(root)
    files = sorted((root / "nutmeg").rglob("*.py"))
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in files]
    tests = [p.read_text(encoding="utf-8", errors="replace")
             for p in sorted((root / "tests").rglob("*.py"))]
    return {
        "nutmeg_py_files": len(files),
        "nutmeg_py_lines": sum(len(t.splitlines()) for t in texts),
        "test_functions": sum(len(_TEST.findall(t)) for t in tests),
        "web_route_decorators": sum(
            len(_ROUTE.findall(t)) for p, t in zip(files, texts, strict=True)
            if "interfaces" in p.parts),
    }


def kernel_stats(db_path: Path | str) -> dict:
    """表数与空表名。以只读方式打开：不建库、不跑迁移。"""
    with sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True) as conn:
        names = [r[0] for r in conn.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' "
            "order by name")]
        empty = [n for n in names
                 if conn.execute(f'select 1 from "{n}" limit 1').fetchone() is None]
    return {"table_count": len(names), "empty_tables": empty}


def launchd_stats(repo_dir: Path | str, installed_dir: Path | str, *,
                  loaded: set[str] | dict[str, str]) -> dict:
    """仓里的定义 vs 已安装目录 vs 此刻装载（`loaded` 来自 `launchctl list`）。"""
    from nutmeg.decision.ops_status import uninstalled_definitions

    defined = sorted(p.stem for p in Path(repo_dir).glob("com.nutmeg.*.plist"))
    installed = {p.stem for p in Path(installed_dir).glob("com.nutmeg.*.plist")}
    return {
        "defined": len(defined),
        "installed": len(installed & set(defined)),
        "loaded": sum(label in loaded for label in defined),
        "uninstalled": [{"label": label, "loaded": is_loaded} for label, is_loaded
                        in uninstalled_definitions(Path(repo_dir), Path(installed_dir),
                                                   loaded=loaded)],
        "not_loaded": [label for label in defined if label not in loaded],
    }


def runs_stats(data_dir: Path | str, *, since: str) -> dict:
    """`logs/runs.jsonl` 里 `since`（含）之后各作业的段数：exit=0 记 ok，其余记 failed。"""
    jobs: dict[str, dict[str, int]] = {}
    path = Path(data_dir) / "logs" / "runs.jsonl"
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict) or str(row.get("ts") or "")[:10] < since:
            continue
        bucket = jobs.setdefault(str(row.get("label")), {"ok": 0, "failed": 0})
        bucket["ok" if row.get("exit") == 0 else "failed"] += 1
    ordered = sorted(jobs.items(), key=lambda kv: (-kv[1]["failed"], kv[0]))
    return {"since": since, "jobs": dict(ordered)}


def inbox_stats(rows: list[dict]) -> dict:
    pending = [r for r in rows if r.get("status") == "pending"]
    return {"pending": len(pending), "overdue": sum(bool(r.get("overdue")) for r in pending),
            "oldest_days": max((int(r.get("age_days") or 0) for r in pending), default=0)}


def rsi_stats(data_dir: Path | str, registry_dir: Path | str) -> dict:
    """与实验室页同一份（`lab.lab_board`）：在跑 / 已结或退役，以及各证据标签的个数。"""
    from collections import Counter

    from nutmeg.decision.lab import lab_board

    board = lab_board(data_dir, registry_dir)
    if board["errors"] and not (board["live"] or board["settled"]):
        raise RuntimeError("；".join(board["errors"])[:200])
    rows = [*board["live"], *board["settled"]]
    return {"registered": len(rows), "live": len(board["live"]),
            "settled": len(board["settled"]),
            "by_label": dict(Counter(str(r.get("label")) for r in rows).most_common())}


def snapshot(blocks: dict[str, Callable[[], dict]], *, captured_at: str) -> dict:
    """逐块取数；某块抛错只在该块记 `_error`（读不出要看得见，不能读成 0）。"""
    out: dict = {"captured_at": captured_at}
    for name, fn in blocks.items():
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001 —— 一块坏了不拖垮整份快照
            out[name] = {"_error": repr(exc)[:200]}
    return out
