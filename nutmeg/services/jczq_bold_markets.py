"""体彩 multi-market math for the bold-combo engine — pure, no I/O, no model.

The 比分 (crs) market is the finest-grained 体彩 market: 胜平负 / 总进球 / 让球
are each a deterministic aggregation of the scoreline distribution. These
helpers de-vig the 体彩 crs odds and aggregate them — the basis of the spec §3
「盘口内部一致性冲突」 signal (the 体彩 board disagreeing with itself).

This module imports NO predictive model and performs NO I/O.
"""

from __future__ import annotations

import re

# A crs odds key is an exact scoreline ``sHHsAA`` (zero-padded goal counts) ...
_RE_CRS_EXACT = re.compile(r"^s(\d{2})s(\d{2})$")
# ... or a lumped 其他 bucket: ``s1sh`` 胜其他 / ``s1sd`` 平其他 / ``s1sa`` 负其他.
_RE_CRS_OTHER = re.compile(r"^s1s([hda])$")
# 其他 bucket letter → the 胜平负 outcome it unambiguously belongs to.
_CRS_OTHER_TO_HAD: dict[str, str] = {"h": "home", "d": "draw", "a": "away"}

# 总进球 buckets — total_0..total_7 (total_7 is the 7+ bucket). Mirrors the
# Sporttery ttg pool keys s0..s7.
TTG_BUCKETS: tuple[str, ...] = tuple(f"total_{k}" for k in range(8))


def crs_scoreline_distribution(
    crs_odds: dict[str, float],
) -> tuple[dict[tuple[int, int], float], dict[str, float]]:
    """De-vig a 体彩 crs pool into a scoreline distribution.

    ``crs_odds`` maps raw Sporttery crs keys (``sHHsAA`` exact, ``s1sX`` 其他;
    the ``...f`` flag keys must already be excluded by the caller) to decimal
    odds. Returns ``(exact, other)``: ``exact`` maps ``(home_goals,
    away_goals)`` → probability, ``other`` maps ``"home"/"draw"/"away"`` →
    probability for the lumped 其他 buckets. The two together de-vig to sum ~1.
    Empty / unusable input → two empty dicts (graceful degradation).
    """
    inverse_exact: dict[tuple[int, int], float] = {}
    inverse_other: dict[str, float] = {}
    for key, odds in crs_odds.items():
        if not odds or odds <= 0:
            continue
        exact_m = _RE_CRS_EXACT.match(key)
        if exact_m:
            score = (int(exact_m.group(1)), int(exact_m.group(2)))
            inverse_exact[score] = 1.0 / odds
            continue
        other_m = _RE_CRS_OTHER.match(key)
        if other_m:
            inverse_other[_CRS_OTHER_TO_HAD[other_m.group(1)]] = 1.0 / odds
    total = sum(inverse_exact.values()) + sum(inverse_other.values())
    if total <= 0:
        return {}, {}
    exact = {k: v / total for k, v in inverse_exact.items()}
    other = {k: v / total for k, v in inverse_other.items()}
    return exact, other


def aggregate_crs_to_had(
    exact: dict[tuple[int, int], float], other: dict[str, float]
) -> dict[str, float]:
    """Aggregate a crs scoreline distribution into 胜平负 probabilities.

    Every crs outcome has a definite 主/平/客 sign — exact scorelines by
    ``home_goals`` vs ``away_goals``, the 其他 buckets by construction — so this
    aggregation is exact (spec §3: crs→had 聚合干净). Sums to ~1.
    """
    had = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (home_goals, away_goals), prob in exact.items():
        if home_goals > away_goals:
            had["home"] += prob
        elif home_goals == away_goals:
            had["draw"] += prob
        else:
            had["away"] += prob
    for outcome, prob in other.items():
        had[outcome] += prob
    return had
