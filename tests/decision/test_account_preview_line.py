"""月账第二行：买前预审覆盖率（接线在 `account.month_report` / `render_month`）。"""
from __future__ import annotations

from pathlib import Path


def test_month_account_prints_the_coverage_line_after_the_effective_room_line(tmp_path: Path):
    from nutmeg.decision.account import month_report, render_month

    report = month_report(tmp_path, "2026-11", with_draft=False, with_rule_v3=False)
    assert report["preview_coverage"] == {"n": 0, "covered": 0, "missing": []}
    lines = render_month(report).splitlines()
    # 第二行仍是实质余量（分析包与播报按约定只读它），买前预审紧随其后
    assert lines[3].startswith("**实质余量")
    assert lines[4] == "**买前预审**：本月没有实购票"
