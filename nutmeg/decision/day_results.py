"""昨日赛果桥：`jczq/jc-results.json`（09:30 回填）→ `daily/<日>/results-90.json`
（betslip settle 的输入）。

只转格式（推导在 `match_results`）；缺终场比分的场进 `missing`，不猜。源头过期时（回填脚本
退出 2）这里自然写不出东西。
"""
from __future__ import annotations

import json
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

from nutmeg.decision.day_paths import RESULTS_90, day_dir
from nutmeg.decision.match_results import day_rows, outcomes


def bridge_results(*, data_dir: Path, date: str) -> dict:
    source_day = (_date.fromisoformat(date) - timedelta(days=1)).isoformat()
    table = day_rows(data_dir, source_day)
    out = outcomes(table)
    missing = [code for code in sorted(table) if code not in out]
    if out:
        target = day_dir(data_dir, date) / RESULTS_90
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    board = Path(data_dir) / "jczq" / "daily" / source_day / "sporttery_markets.json"
    return {"source_day": source_day, "written": len(out), "missing": missing,
            "unsealed": board.exists() and not table}
