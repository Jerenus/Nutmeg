"""worldcup 子包 — 门控与赛制规则测试。"""
from __future__ import annotations

from nutmeg.services.worldcup import is_wc_active


def test_wc_active_inside_window() -> None:
    assert is_wc_active("2026-06-11") is True
    assert is_wc_active("2026-07-19") is True


def test_wc_inactive_outside_window() -> None:
    assert is_wc_active("2026-06-10") is False
    assert is_wc_active("2026-07-20") is False
    assert is_wc_active("2027-06-15") is False


def test_wc_active_bad_date_is_false() -> None:
    assert is_wc_active("not-a-date") is False
