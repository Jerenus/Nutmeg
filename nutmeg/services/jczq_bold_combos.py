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
from dataclasses import dataclass, field

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


# ---------------------------------------------------------------------------
# Task 3 — boldness composition + bold-leg selection
# ---------------------------------------------------------------------------

# Signal weights — documented defaults, all equal (0.2). Tunable knobs: raising
# WEIGHT_CONTRARIAN biases the engine toward colder, wilder legs.
WEIGHT_CONFLICT: float = 0.2
WEIGHT_CONTRARIAN: float = 0.2
WEIGHT_DRIFT: float = 0.2
WEIGHT_DISPERSION: float = 0.2
WEIGHT_HEAT: float = 0.2

# Human-readable Chinese labels for each signal — used in the 大胆理由 string.
_SIGNAL_LABELS: dict[str, str] = {
    "conflict": "盘口冲突",
    "contrarian": "反直觉冷门",
    "drift": "欧赔漂移",
    "dispersion": "博彩离散",
    "heat": "盘面热度",
}

# Outcome → Chinese 胜平负 label.
OUTCOME_LABELS: dict[str, str] = {"home": "胜", "draw": "平", "away": "负"}


@dataclass(slots=True, frozen=True)
class BoldMatch:
    """One match's board inputs for the bold engine — 体彩 odds + 欧赔 only.

    NO predictive-model fields (no xG / form / H2H) — that would smuggle the
    retired model back in (spec §3, §8). ``euro_odds`` / ``euro_opening`` /
    ``per_book_odds`` are empty dicts when 欧赔 is unavailable; the conflict /
    drift / dispersion signals then degrade to 0 (heat + contrarian still work).
    """

    match_no: str
    league: str
    home: str
    away: str
    tc_odds: dict[str, float]
    euro_odds: dict[str, float] = field(default_factory=dict)
    euro_opening: dict[str, float] = field(default_factory=dict)
    per_book_odds: dict[str, list[float]] = field(default_factory=dict)
    tags: set[str] = field(default_factory=set)
    vig: float = 0.12


@dataclass(slots=True, frozen=True)
class BoldLeg:
    """One bold 1X2 pick for one match — the unit a parlay is built from.

    ``boldness`` is a heuristic salience score, NOT a probability. ``reason``
    is a human-readable Chinese string naming the dominant board signal.
    """

    match_no: str
    league: str
    home: str
    away: str
    pick: str
    tc_odds: float
    boldness: float
    reason: str


def _fair_from_odds(odds: dict[str, float]) -> dict[str, float]:
    """De-vig decimal odds to fair probabilities summing to ~1.

    Returns an empty dict when ``odds`` is empty/unusable — callers treat that
    as "signal unavailable" (graceful degradation)."""
    inverse = {
        o: 1.0 / odds[o]
        for o in OUTCOMES
        if odds.get(o) and odds[o] > 0
    }
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {o: v / total for o, v in inverse.items()}


def boldness(match: BoldMatch) -> dict[str, float]:
    """Compose the five board signals into a per-outcome boldness score.

    ``WEIGHT_CONFLICT*conflict + WEIGHT_CONTRARIAN*contrarian +
    WEIGHT_DRIFT*drift + WEIGHT_DISPERSION*dispersion + WEIGHT_HEAT*heat`` —
    the heat term is the per-match scalar added uniformly to every outcome.
    """
    tc_fair = _fair_from_odds(match.tc_odds)
    euro_fair = _fair_from_odds(match.euro_odds)

    conflict = conflict_score(tc_fair, euro_fair)
    contrarian = contrarian_score(tc_fair)
    drift = drift_score(match.euro_opening, match.euro_odds)
    dispersion = dispersion_score(match.per_book_odds)
    heat = heat_score(match.tags, match.vig)

    return {
        o: (
            WEIGHT_CONFLICT * conflict[o]
            + WEIGHT_CONTRARIAN * contrarian[o]
            + WEIGHT_DRIFT * drift[o]
            + WEIGHT_DISPERSION * dispersion[o]
            + WEIGHT_HEAT * heat
        )
        for o in OUTCOMES
    }


def _dominant_signal(match: BoldMatch, pick: str) -> str:
    """Return the Chinese label of the signal contributing most to ``pick``."""
    tc_fair = _fair_from_odds(match.tc_odds)
    euro_fair = _fair_from_odds(match.euro_odds)
    contributions = {
        "conflict": WEIGHT_CONFLICT * conflict_score(tc_fair, euro_fair)[pick],
        "contrarian": WEIGHT_CONTRARIAN * contrarian_score(tc_fair)[pick],
        "drift": WEIGHT_DRIFT * drift_score(match.euro_opening, match.euro_odds)[pick],
        "dispersion": WEIGHT_DISPERSION * dispersion_score(match.per_book_odds)[pick],
        "heat": WEIGHT_HEAT * heat_score(match.tags, match.vig),
    }
    top = max(contributions, key=lambda k: contributions[k])
    return _SIGNAL_LABELS[top]


def bold_leg(match: BoldMatch) -> BoldLeg:
    """Pick the highest-boldness outcome for ``match`` as its bold leg.

    The ``reason`` names the dominant board signal — a human-readable hook for
    the entertainment narrative, never a claim of advantage.
    """
    scores = boldness(match)
    pick = max(OUTCOMES, key=lambda o: scores[o])
    signal = _dominant_signal(match, pick)
    outcome_label = OUTCOME_LABELS[pick]
    reason = f"{outcome_label}向 · 主导信号「{signal}」"
    return BoldLeg(
        match_no=match.match_no,
        league=match.league,
        home=match.home,
        away=match.away,
        pick=pick,
        tc_odds=match.tc_odds.get(pick, 0.0),
        boldness=scores[pick],
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Task 4 — day-level chaos value (spec §3.5)
# ---------------------------------------------------------------------------

# CHAOS_SCALE maps a per-match uncertainty (mean dispersion + mean conflict,
# roughly [0, 2]) onto the 0-100 chaos scale. Documented default.
CHAOS_SCALE: float = 50.0
# The candidate-pool size bounds — documented defaults (spec / plan §4).
POOL_MIN: int = 4
POOL_MAX: int = 10


def _match_uncertainty(match: BoldMatch) -> float:
    """One match's uncertainty: ``mean(dispersion) + mean(conflict)`` over the
    three outcomes — the §3.5 building block of the day chaos value."""
    tc_fair = _fair_from_odds(match.tc_odds)
    euro_fair = _fair_from_odds(match.euro_odds)
    conflict = conflict_score(tc_fair, euro_fair)
    dispersion = dispersion_score(match.per_book_odds)
    mean_conflict = sum(conflict.values()) / len(OUTCOMES)
    mean_dispersion = sum(dispersion.values()) / len(OUTCOMES)
    return mean_conflict + mean_dispersion


def day_chaos(matches: list[BoldMatch]) -> int:
    """Aggregate the day's matches into a single 0-100 大盘面混乱值.

    Per match → an uncertainty (``_match_uncertainty``); the day value is the
    *median* uncertainty scaled by ``CHAOS_SCALE``, rounded and clamped to
    [0, 100]. The median (not the mean) keeps one freak match from dominating.
    An empty day → 0 (calm), never a crash.
    """
    if not matches:
        return 0
    uncertainties = sorted(_match_uncertainty(m) for m in matches)
    median = statistics.median(uncertainties)
    return max(0, min(100, round(median * CHAOS_SCALE)))


def chaos_pool_size(chaos: int) -> int:
    """Map the day chaos value to the candidate-pool size ``N``.

    Linear from ``POOL_MIN`` at chaos 0 to ``POOL_MAX`` at chaos 100 — a calm
    day picks from a small, restrained pool; a chaotic day from a big, wild one.
    """
    chaos = max(0, min(100, chaos))
    span = POOL_MAX - POOL_MIN
    return POOL_MIN + round(span * chaos / 100)


def chaos_band(chaos: int) -> str:
    """Label the day chaos value: 平静 (< 34) / 中等 (34-66) / 混乱 (> 66)."""
    if chaos < 34:
        return "平静"
    if chaos <= 66:
        return "中等"
    return "混乱"
