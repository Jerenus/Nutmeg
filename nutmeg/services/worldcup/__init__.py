"""世界杯 2026 专题层 — spec docs/superpowers/specs/2026-06-11-jczq-worldcup-2026-design.md。

门控原则(spec §9):窗口外本包对管线零影响,7/19 后自动退役。
"""
from __future__ import annotations

from datetime import date

WC_WINDOW_START = date(2026, 6, 11)
WC_WINDOW_END = date(2026, 7, 19)


def is_wc_active(run_date: str) -> bool:
    """世界杯窗口门控 — 解析失败一律 False(绝不让坏日期把世界杯层拉起来)。"""
    try:
        d = date.fromisoformat(run_date)
    except (TypeError, ValueError):
        return False
    return WC_WINDOW_START <= d <= WC_WINDOW_END
