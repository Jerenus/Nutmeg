"""夜间结果校准（确定性算术层）。

胜负彩 90 分钟口径：AET/PEN 一律取 score.fulltime（26095/26111 场5 口径纪律）。
身份纪律：match_no → fixture_id 必须来自 {issue}-af-map.json 显式映射，
缺失即显式跳过，禁止按队名猜测回退（Intelligence OS 不变量）。
本模块不写 rx、不写 scoreboard——判断与复盘留在主循环。
"""
from __future__ import annotations

import json
from pathlib import Path

_FINISHED = {"FT", "AET", "PEN"}


def result_code(ft_home: int, ft_away: int) -> str:
    """90 分钟比分 → 彩果 3/1/0。"""
    if ft_home > ft_away:
        return "3"
    if ft_home == ft_away:
        return "1"
    return "0"


def load_af_map(zucai_dir, issue: str) -> dict[str, int]:
    """{issue}-af-map.json → {match_no(str): fixture_id(int)}。缺文件=空映射（全场显式跳过）。"""
    path = Path(zucai_dir) / f"{issue}-af-map.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text("utf-8"))
    return {str(k): int(v) for k, v in (data.get("fixtures") or {}).items()}
