"""Bold-combo engine — an ENTERTAINMENT-purpose JCZQ parlay generator.

⚠️ HONEST FRAMING (spec §0 — welded into the product on purpose)

A 2026-05-18 188-match point-in-time backtest proved the predictive model
(Dixon-Coles) loses to the betting market (46.8% vs 56.4%) and the conflict
engine has no edge. 竞彩 takes roughly a 13% cut. **This engine is not a
money-making tool — it is an entertainment tool.** The user chose to build it
knowing those facts. It does NOT predict winners, does NOT claim an edge, and
its long-run expectation is negative.

What it does instead: from real *board* signals (体彩-vs-欧赔 conflict,
contrarian direction, market heat, odds drift, bookmaker dispersion) it picks a
bold 1X2 leg per match and assembles creative 3/4/5-fold parlays, modulated by
a day-level chaos value. Every output carries the welded 🎲 label and contains
NO advantage wording ("胜率 / edge / +EV / 正期望 / 推荐下注 / 重仓" are banned).

**This module deliberately imports NO predictive model** — not ``dixon_coles``,
not ``ValueBoardService``. It consumes only 体彩 odds + 欧赔. That is asserted
by a test (spec §7).

The "大胆分" (boldness score) is a heuristic *salience* score, NOT a
probability. It is never labelled "胜率 / 信心".
"""

from __future__ import annotations

import statistics

# The single outcome vocabulary used everywhere in this module — the 胜平负
# (1X2) market, the only market where 体彩 odds and 欧赔 both exist cleanly.
OUTCOMES: tuple[str, str, str] = ("home", "draw", "away")

# --- Named-constant signal gains (documented defaults — tunables) ----------
# Drift: an implied-probability move of ~0.10 (a sizeable shift) maps to ~0.6.
DRIFT_GAIN: float = 6.0
# Dispersion: a population stdev of 1/odds around ~0.05 across books maps high.
DISPERSION_GAIN: float = 12.0
# Heat: each present board tag contributes this much.
HEAT_TAG: float = 0.25
# Heat: 体彩 vig above the ~0.12 baseline contributes this per unit of excess.
HEAT_VIG_GAIN: float = 4.0

# Board tags from the brief's §1 table that read as "heat".
HEAT_TAGS: frozenset[str] = frozenset(
    {"强胆场", "舒服盘", "coinflip", "draw_friendly", "hi-vol"}
)


def _clip01(value: float) -> float:
    """Clamp a score to the [0, 1] interval."""
    return max(0.0, min(1.0, value))


def conflict_score(
    tc_fair: dict[str, float], euro_fair: dict[str, float]
) -> dict[str, float]:
    """Per-outcome disagreement between the 体彩 fair probability and the 欧赔
    fair probability — ``abs(tc_fair[o] - euro_fair[o])``, clipped to [0, 1].

    The bigger the gap between the 体彩 board you bet on and the smarter
    international board, the more there is to "dig into". Missing 欧赔 → empty
    ``euro_fair`` → the signal degrades to 0 for every outcome (never a crash).
    """
    if not euro_fair:
        return {o: 0.0 for o in OUTCOMES}
    return {
        o: _clip01(abs(tc_fair.get(o, 0.0) - euro_fair.get(o, 0.0)))
        for o in OUTCOMES
    }


def contrarian_score(tc_fair: dict[str, float]) -> dict[str, float]:
    """Reward outcomes that run *against* the 体彩 hot direction.

    The 体彩 favorite (argmax of ``tc_fair``) scores 0.0 — backing it is the
    opposite of contrarian. Each non-favorite outcome scores ``1 - tc_fair[o]``
    — the colder it is, the bolder it is to pick.
    """
    if not tc_fair:
        return {o: 0.0 for o in OUTCOMES}
    favorite = max(OUTCOMES, key=lambda o: tc_fair.get(o, 0.0))
    return {
        o: 0.0 if o == favorite else _clip01(1.0 - tc_fair.get(o, 0.0))
        for o in OUTCOMES
    }


def drift_score(
    opening: dict[str, float], live: dict[str, float]
) -> dict[str, float]:
    """Per-outcome 欧赔 implied-probability movement from opening to live odds.

    ``min(abs(1/live[o] - 1/opening[o]) * DRIFT_GAIN, 1.0)`` — the more the
    international market changed its mind, the more there is "in play". Missing
    opening or live odds → the signal degrades to 0 (never a crash).
    """
    if not opening or not live:
        return {o: 0.0 for o in OUTCOMES}
    result: dict[str, float] = {}
    for o in OUTCOMES:
        open_o = opening.get(o)
        live_o = live.get(o)
        if not open_o or not live_o or open_o <= 0 or live_o <= 0:
            result[o] = 0.0
            continue
        move = abs(1.0 / live_o - 1.0 / open_o)
        result[o] = _clip01(move * DRIFT_GAIN)
    return result


def dispersion_score(per_book_odds: dict[str, list[float]]) -> dict[str, float]:
    """Per-outcome population stdev of ``1/odds`` across the ~29 international
    books, ``* DISPERSION_GAIN``, clipped to [0, 1].

    Professional books arguing loudly about a match is its own "chaos" signal
    (and a component of the day-level chaos value, §3.5). Missing per-book data
    → the signal degrades to 0 (never a crash).
    """
    if not per_book_odds:
        return {o: 0.0 for o in OUTCOMES}
    result: dict[str, float] = {}
    for o in OUTCOMES:
        books = [b for b in per_book_odds.get(o, []) if b and b > 0]
        if len(books) < 2:
            result[o] = 0.0
            continue
        implied = [1.0 / b for b in books]
        result[o] = _clip01(statistics.pstdev(implied) * DISPERSION_GAIN)
    return result


def heat_score(match_tags: set[str], vig: float) -> float:
    """A per-MATCH scalar heat score from the brief's §1 board tags + 体彩 vig.

    ``+HEAT_TAG`` for each present heat tag (强胆场 / 舒服盘 / coinflip /
    draw_friendly / hi-vol), plus ``(vig - 0.12) * HEAT_VIG_GAIN`` for 体彩 vig
    above the ~0.12 baseline. Clipped to [0, 1]. Works with NO 欧赔 — heat is a
    pure 体彩-side signal.
    """
    tag_hits = sum(1 for tag in match_tags if tag in HEAT_TAGS)
    raw = tag_hits * HEAT_TAG + (vig - 0.12) * HEAT_VIG_GAIN
    return _clip01(raw)
