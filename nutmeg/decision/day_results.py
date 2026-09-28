"""昨日赛果桥：`jczq/jc-results.json`（09:30 回填）→ `daily/<日>/results-90.json`
（betslip settle 的输入）。

只转格式；缺终场比分的场进 `missing`，不猜。源头过期时（回填脚本退出 2）这里自然写不出东西。
"""
from __future__ import annotations

import json
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

from nutmeg.decision.day_paths import RESULTS_90, day_dir


def outcome_90(goals_h: int, goals_a: int) -> str:
    return "3" if goals_h > goals_a else ("1" if goals_h == goals_a else "0")


def bridge_results(*, data_dir: Path, date: str) -> dict:
    source_day = (_date.fromisoformat(date) - timedelta(days=1)).isoformat()
    path = Path(data_dir) / "jczq" / "jc-results.json"
    try:
        table = json.loads(path.read_text(encoding="utf-8")).get(source_day) or {}
    except (FileNotFoundError, ValueError):
        table = {}
    out: dict[str, dict] = {}
    missing: list[str] = []
    for code, row in sorted(table.items()):
        gh, ga = row.get("ft_home"), row.get("ft_away")
        if gh is None or ga is None:
            missing.append(code)
            continue
        out[code] = {
            "outcome_90": outcome_90(int(gh), int(ga)),
            "goals_h": int(gh),
            "goals_a": int(ga),
        }
    if out:
        target = day_dir(data_dir, date) / RESULTS_90
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    board = Path(data_dir) / "jczq" / "daily" / source_day / "sporttery_markets.json"
    return {"source_day": source_day, "written": len(out), "missing": missing,
            "unsealed": board.exists() and not table}
