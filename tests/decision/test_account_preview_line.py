"""月账第二行：买前预审覆盖率（接线在 `account.month_report` / `render_month`）。"""
from __future__ import annotations

from pathlib import Path


def test_month_account_prints_the_coverage_line_right_under_the_headline(tmp_path: Path):
    from nutmeg.decision.account import month_report, render_month

    report = month_report(tmp_path, "2026-11", with_draft=False, with_rule_v3=False)
    assert report["preview_coverage"] == {"n": 0, "covered": 0, "missing": []}
    lines = render_month(report).splitlines()
    assert lines[3] == "**买前预审**：本月没有实购票"
