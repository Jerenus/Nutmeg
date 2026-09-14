"""单测影子期对比 —— 逐场逐路比 fair，出可读报告。无网络。"""

from __future__ import annotations

import pytest

from nutmeg.data.fcom500 import MarketOdds
from nutmeg.decision.odds_shadow import compare_sources, render_report


def _market(odds: dict[str, float], *, opening: dict[str, float] | None = None, books: int = 10):
    fair_total = sum(1 / v for v in odds.values())
    return MarketOdds(
        odds=odds,
        fair_probability={k: round((1 / v) / fair_total, 6) for k, v in odds.items()},
        independent=True,
        bookmaker_count=books,
        opening_odds=opening or {},
    )


def test_compare_reports_coverage_of_each_source():
    board = ["周一002", "周一003", "周一004"]
    rows = compare_sources(
        board,
        {"周一002": {"match_winner": _market({"home": 1.7, "draw": 3.8, "away": 5.0})}},
        {
            "周一002": {"match_winner": _market({"home": 1.72, "draw": 3.75, "away": 4.9})},
            "周一003": {"match_winner": _market({"home": 2.1, "draw": 3.3, "away": 3.5})},
        },
    )
    assert [r.match_no for r in rows] == board
    assert rows[0].baseline_fair is not None and rows[0].candidate_fair is not None
    assert rows[1].baseline_fair is None and rows[1].candidate_fair is not None
    assert rows[2].baseline_fair is None and rows[2].candidate_fair is None


def test_compare_computes_max_absolute_fair_delta_in_pp():
    rows = compare_sources(
        ["周一002"],
        {"周一002": {"match_winner": _market({"home": 2.0, "draw": 4.0, "away": 4.0})}},
        {"周一002": {"match_winner": _market({"home": 2.5, "draw": 4.0, "away": 4.0})}},
    )
    # baseline fair home = .5, candidate fair home = .4444 → 5.56pp
    assert rows[0].max_delta_pp == pytest.approx(5.56, abs=0.05)


def test_report_names_both_coverage_counts_and_the_drift_capability():
    rows = compare_sources(
        ["周一002", "周一003"],
        {"周一002": {"match_winner": _market({"home": 1.7, "draw": 3.8, "away": 5.0})}},
        {
            "周一002": {
                "match_winner": _market(
                    {"home": 1.72, "draw": 3.75, "away": 4.9},
                    opening={"home": 2.0, "draw": 3.4, "away": 3.6},
                )
            },
            "周一003": {
                "match_winner": _market(
                    {"home": 2.1, "draw": 3.3, "away": 3.5},
                    opening={"home": 2.2, "draw": 3.3, "away": 3.3},
                )
            },
        },
    )
    report = render_report("2026-09-14", rows)
    assert "1/2" in report  # baseline 覆盖
    assert "2/2" in report  # candidate 覆盖
    assert "初赔" in report
