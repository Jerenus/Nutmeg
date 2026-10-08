"""竞彩 90' 赛果：唯一来源、唯一推导（2026-10-08 第二轮瘦身 B1）。

来源只有一个：`jczq/jc-results.json`。`scripts/jczq_result_backfill.py` 每天 09:30 / 15:30
从 jc.titan007.com 的竞彩赛果页回填，整板踢完（或板面日已过 3 天）才封存一天。
结构 = {竞彩板面日: {竞彩编号: {ft_home, ft_away, ht_home, ht_away, match_id, line}}}，
90' 口径（加时 / 点球不计）。设计系列 ⑥（2026-10-01）起夜账走它；本轮起内核结算
（`ontology_adapter._results_v2`）、昨日赛果桥（`day_results`）、复盘编码（`retro_encoder`）、
判决页信号（`signals`）、过程回放（`observe_history`）、夜账校准（`zucai_night`）都只经本模块
读它。此前六处各算一遍，内核另走 okooo + 当日体彩快照：快照会丢已完场的场次，内核因此
整板缺赛果（2026-09-01 起与 jc-results 比分 390/390 一致，但内核少 27 场）。
"""
from __future__ import annotations

import json
from pathlib import Path

JC_RESULTS = Path("jczq") / "jc-results.json"


def outcome_90(goals_h: int, goals_a: int) -> str:
    """90' 比分 → 竞彩胜平负彩果 3 / 1 / 0。"""
    if goals_h > goals_a:
        return "3"
    if goals_h == goals_a:
        return "1"
    return "0"


def day_rows(data_dir, day: str) -> dict[str, dict]:
    """板面日 day 的原始赛果行 {竞彩编号: row}；文件缺失 / 损坏 / 当日未封存 → {}。"""
    try:
        table = json.loads((Path(data_dir) / JC_RESULTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = table.get(day) if isinstance(table, dict) else None
    return rows if isinstance(rows, dict) else {}


def outcomes(rows: dict[str, dict]) -> dict[str, dict]:
    """原始行 → {竞彩编号: {"outcome_90", "goals_h", "goals_a"}}（编号升序）；

    缺终场比分的场不进表。"""
    out: dict[str, dict] = {}
    for code, row in sorted(rows.items()):
        gh, ga = (row or {}).get("ft_home"), (row or {}).get("ft_away")
        if gh is None or ga is None:
            continue
        out[code] = {"outcome_90": outcome_90(int(gh), int(ga)),
                     "goals_h": int(gh), "goals_a": int(ga)}
    return out


def board_outcomes(data_dir, day: str) -> dict[str, dict]:
    """板面日 day 的 90' 赛果 {竞彩编号: {"outcome_90", "goals_h", "goals_a"}}；未封存 → {}。"""
    return outcomes(day_rows(data_dir, day))
