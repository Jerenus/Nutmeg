"""Tests for the bold-combo engine (`nutmeg/services/jczq_bold_combos.py`).

An ENTERTAINMENT-purpose JCZQ parlay generator — no predictive model, no edge.
These tests pin the five board signals, the boldness composition, the day
chaos value, the combination generator, and — critically — the welded honest
label + the no-advantage-wording acceptance assertions (spec §7).
"""

from __future__ import annotations

import math

from nutmeg.services.jczq_bold_combos import (
    OUTCOMES,
    conflict_score,
    contrarian_score,
    dispersion_score,
    drift_score,
    heat_score,
)


# ---------------------------------------------------------------------------
# Task 2 — the five board-signal scoring functions
# ---------------------------------------------------------------------------


def test_outcomes_vocabulary() -> None:
    assert OUTCOMES == ("home", "draw", "away")


def test_conflict_score_is_absolute_fair_prob_gap() -> None:
    tc_fair = {"home": 0.30, "draw": 0.35, "away": 0.35}
    euro_fair = {"home": 0.45, "draw": 0.30, "away": 0.25}

    score = conflict_score(tc_fair, euro_fair)

    assert math.isclose(score["home"], 0.15, abs_tol=1e-9)
    assert math.isclose(score["draw"], 0.05, abs_tol=1e-9)
    assert math.isclose(score["away"], 0.10, abs_tol=1e-9)


def test_conflict_score_clips_to_unit_interval() -> None:
    score = conflict_score(
        {"home": 0.99, "draw": 0.005, "away": 0.005},
        {"home": 0.0, "draw": 0.5, "away": 0.5},
    )
    assert all(0.0 <= v <= 1.0 for v in score.values())


def test_conflict_score_degrades_to_zero_without_euro() -> None:
    """Missing 欧赔 → empty euro_fair → conflict signal is 0, never a crash."""
    score = conflict_score({"home": 0.4, "draw": 0.3, "away": 0.3}, {})
    assert score == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_contrarian_score_rewards_non_favorite_outcomes() -> None:
    tc_fair = {"home": 0.55, "draw": 0.25, "away": 0.20}

    score = contrarian_score(tc_fair)

    assert score["home"] == 0.0  # 体彩 favorite — never contrarian
    assert math.isclose(score["draw"], 0.75, abs_tol=1e-9)
    assert math.isclose(score["away"], 0.80, abs_tol=1e-9)


def test_drift_score_measures_implied_probability_movement() -> None:
    opening = {"home": 2.0, "draw": 3.4, "away": 3.4}
    live = {"home": 1.6, "draw": 3.4, "away": 3.4}

    score = drift_score(opening, live)

    assert score["home"] > 0.0  # the market moved on home
    assert score["draw"] == 0.0  # unchanged
    assert score["away"] == 0.0
    assert all(0.0 <= v <= 1.0 for v in score.values())


def test_drift_score_degrades_to_zero_without_opening() -> None:
    score = drift_score({}, {"home": 1.6, "draw": 3.4, "away": 3.4})
    assert score == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_dispersion_score_zero_when_books_agree() -> None:
    per_book = {
        "home": [2.0, 2.0, 2.0],
        "draw": [3.3, 3.3, 3.3],
        "away": [3.5, 3.5, 3.5],
    }
    score = dispersion_score(per_book)
    assert score == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_dispersion_score_positive_when_books_disagree() -> None:
    per_book = {
        "home": [1.5, 2.0, 2.8],
        "draw": [3.3, 3.3, 3.3],
        "away": [3.5, 3.5, 3.5],
    }
    score = dispersion_score(per_book)
    assert score["home"] > 0.0
    assert score["draw"] == 0.0
    assert all(0.0 <= v <= 1.0 for v in score.values())


def test_dispersion_score_degrades_to_zero_without_books() -> None:
    score = dispersion_score({})
    assert score == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_heat_score_combines_tags_and_vig() -> None:
    from nutmeg.services.jczq_bold_combos import HEAT_TAG, HEAT_VIG_GAIN

    score = heat_score({"强胆场", "hi-vol"}, vig=0.13)

    expected = 2 * HEAT_TAG + (0.13 - 0.12) * HEAT_VIG_GAIN
    assert math.isclose(score, min(expected, 1.0), abs_tol=1e-9)


def test_heat_score_ignores_unknown_tags_and_clips() -> None:
    score = heat_score({"not-a-real-tag"}, vig=0.0)
    assert 0.0 <= score <= 1.0
