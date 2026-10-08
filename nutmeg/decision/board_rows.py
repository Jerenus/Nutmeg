"""竞彩板面「每场一行」的唯一构建处（2026-10-08 第二轮瘦身 B4）。

当日报告卡片（`day_brief._jczq`）、初判包（`judgment_brief.jczq_brief`）、信号面板
（`signals.build_signals`）原先各读一遍 legs-base / reads.json / price-band / 终盘 / 研究文件、
各自按 match_id 配 Read，口径慢慢走散（reads.json 里的非对象行、旧格式研究文件，三处处理各不相同）。
现在三处都从这里取同一份行，再各自投影成自己的列。只读文件，不碰内核、不写判断。
"""
from __future__ import annotations

import json
from pathlib import Path


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def jczq_rows(data_dir, day: str, *, legs: dict | None = None) -> list[dict]:
    """板面日 day 的每场输入，legs-base 原顺序（初判包 / 信号按编号排，当日报告按开球排）。

    每行 = {code, leg（legs-base 原样）, read（reads.json 按 match_id 配，缺 → {}）,
    band（price-band-<编号>.json，缺 → {}）, closing（closing_odds.json[编号]，缺 → {}）,
    research（research-<编号>.json；缺或旧格式非对象 → None）}。
    `legs` 给出时用它（调用方已读过 legs-base 并自行报缺失），否则读 legs-base（缺 → 空板）。
    """
    day_dir = Path(data_dir) / "jczq" / "daily" / day
    if legs is None:
        legs = (_read(day_dir / "jczq-legs-base.json", {}) or {}).get("legs") or {}
    reads = {r.get("match_id"): r for r in (_read(day_dir / "reads.json", []) or [])
             if isinstance(r, dict)}
    closing = _read(day_dir / "closing_odds.json", {}) or {}
    rows = []
    for code, leg in legs.items():
        research = _read(day_dir / f"research-{code}.json", None)
        rows.append({
            "code": code, "leg": leg,
            "read": reads.get(leg.get("match_id")) or {},
            "band": _read(day_dir / f"price-band-{code}.json", {}) or {},
            "closing": closing.get(code) or {},
            "research": research if isinstance(research, dict) else None,
        })
    return rows


def fmt_stance(stance: dict | None, *, empty: str = "—") -> str:
    """表态一格：「押{首选面}·{面集合}」；没表态 → `empty`（当日报告「—」，会话入口「未表态」）。"""
    if not stance or not stance.get("face"):
        return empty
    return f"押{stance['face']}·{stance.get('faces') or stance['face']}"
