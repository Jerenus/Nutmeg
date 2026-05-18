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

import itertools
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from nutmeg.services.jczq_bold_markets import (
    TTG_BUCKETS,
    aggregate_crs_to_had,
    aggregate_crs_to_hhad,
    aggregate_crs_to_ttg,
    aggregate_ttg_to_over_under,
    crs_scoreline_distribution,
)

# The single outcome vocabulary used everywhere in this module — the 胜平负
# (1X2) market, the only market where 体彩 odds and 欧赔 both exist cleanly.
OUTCOMES: tuple[str, str, str] = ("home", "draw", "away")

# --- Multi-market vocabulary (spec: bold-combo multi-market extension) ------
# The four 体彩 markets the engine scores.
MARKETS: tuple[str, ...] = ("had", "hhad", "ttg", "crs")

# Per market, the signals that are ACTIVE. The rest contribute 0 and take no
# weight (per-market weight normalization, spec §3 跨市场可比性). had has all
# five; hhad/crs have three; ttg has four (dispersion from the 大小球 books).
MARKET_SIGNALS: dict[str, tuple[str, ...]] = {
    "had": ("conflict", "contrarian", "drift", "dispersion", "heat"),
    "hhad": ("conflict", "contrarian", "heat"),
    "ttg": ("conflict", "contrarian", "dispersion", "heat"),
    "crs": ("conflict", "contrarian", "heat"),
}

# Human-readable market labels for the renderer.
MARKET_LABELS: dict[str, str] = {
    "had": "胜平负", "hhad": "让球", "ttg": "总进球", "crs": "比分",
}

# A raw Sporttery crs odds key — exact scoreline sHHsAA or an 其他 bucket s1sX.
_RE_CRS_KEY = re.compile(r"^s\d{2}s\d{2}$|^s1s[hda]$")

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


def _devig_map(odds: dict[str, float]) -> dict[str, float]:
    """De-vig an arbitrary-keyed odds map to fair probabilities summing to ~1.

    Generalizes ``_fair_from_odds`` (which is hard-coded to ``OUTCOMES``) to the
    总进球 / 让球 keyspaces. Empty / unusable input → empty dict.
    """
    inverse = {k: 1.0 / v for k, v in odds.items() if v and v > 0}
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in inverse.items()}


def internal_conflict(match: BoldMatch, market: str) -> dict[str, float]:
    """Per-outcome 盘口内部一致性冲突 for ``market`` — the 体彩 board's direct
    quote vs the value derived by aggregating its own crs board.

    ``market`` ∈ {"had", "hhad", "ttg"}. Returns ``{outcome_key: conflict}``,
    each ``abs(direct_fair - crs_derived_fair)`` clipped to [0, 1]. No crs board,
    or no direct quote → all-zero (graceful degradation). The crs market's own
    internal conflict is handled separately in ``_crs_internal_conflict``.
    """
    exact, other = crs_scoreline_distribution(match.crs_odds)
    if not exact and not other:
        outcomes = TTG_BUCKETS if market == "ttg" else OUTCOMES
        return {o: 0.0 for o in outcomes}
    if market == "had":
        derived = aggregate_crs_to_had(exact, other)
        direct = _fair_from_odds(match.had_odds_or_tc())
        keys = OUTCOMES
    elif market == "hhad":
        derived = aggregate_crs_to_hhad(exact, match.hhad_line)
        direct = _fair_from_odds(match.hhad_odds)
        keys = OUTCOMES
    elif market == "ttg":
        derived = aggregate_crs_to_ttg(exact)
        direct = _devig_map(match.ttg_odds)
        keys = TTG_BUCKETS
    else:  # pragma: no cover - defensive
        return {}
    if not direct:
        return {o: 0.0 for o in keys}
    return {
        o: _clip01(abs(direct.get(o, 0.0) - derived.get(o, 0.0))) for o in keys
    }


def external_conflict_ttg(match: BoldMatch) -> float:
    """Scalar 外部冲突 for 总进球 — the 体彩 总进球 board collapsed onto the 大小球
    line vs the international 大小球 board.

    Returns ``abs(体彩 P(over) - 国际 P(over))`` clipped to [0, 1]. No 体彩 ttg
    board, or no 国际大小球 → 0.0 (graceful degradation).
    """
    tc_ttg = _devig_map(match.ttg_odds)
    ou_fair = _devig_map(match.ou_odds)
    if not tc_ttg or not ou_fair or not match.ou_line:
        return 0.0
    tc_over_under = aggregate_ttg_to_over_under(tc_ttg, match.ou_line)
    return _clip01(abs(tc_over_under.get("over", 0.0) - ou_fair.get("over", 0.0)))


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
    # --- multi-market 体彩 odds (default empty → engine scores 胜平负 only) ---
    hhad_odds: dict[str, float] = field(default_factory=dict)   # home/draw/away
    hhad_line: float = 0.0                                       # home handicap, goals
    ttg_odds: dict[str, float] = field(default_factory=dict)     # total_0..total_7
    crs_odds: dict[str, float] = field(default_factory=dict)     # raw sHHsAA / s1sX keys
    ou_odds: dict[str, float] = field(default_factory=dict)      # 国际大小球 over/under
    ou_line: float = 0.0
    ou_per_book: dict[str, list[float]] = field(default_factory=dict)

    def had_odds_or_tc(self) -> dict[str, float]:
        """The 胜平负 体彩 odds — ``tc_odds`` IS the had market (v1 naming kept)."""
        return self.tc_odds


@dataclass(slots=True, frozen=True)
class BoldLeg:
    """One bold pick for one match in one market — the unit a parlay is built from.

    ``boldness`` is a heuristic salience score, NOT a probability. ``market`` is
    one of ``MARKETS``; ``pick`` is the internal outcome key; ``pick_label`` is
    the display string (胜 / 让平 / 3球 / 2:1). ``reason`` names the dominant
    board signal.
    """

    match_no: str
    league: str
    home: str
    away: str
    pick: str
    tc_odds: float
    boldness: float
    reason: str
    market: str = "had"
    pick_label: str = ""


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
# Multi-market — per-market boldness composition + per-market bold leg
# ---------------------------------------------------------------------------

# Weight lookup by signal name — for per-market normalization.
_SIGNAL_WEIGHTS: dict[str, float] = {
    "conflict": WEIGHT_CONFLICT,
    "contrarian": WEIGHT_CONTRARIAN,
    "drift": WEIGHT_DRIFT,
    "dispersion": WEIGHT_DISPERSION,
    "heat": WEIGHT_HEAT,
}

# crs pick label "H:A" from a raw sHHsAA key, and the 其他 buckets.
_CRS_OTHER_LABELS: dict[str, str] = {"s1sh": "胜其他", "s1sd": "平其他", "s1sa": "负其他"}
# ttg pick label from a total_K key.
_TTG_LABELS: dict[str, str] = {f"total_{k}": f"{k}球" for k in range(7)}
_TTG_LABELS["total_7"] = "7+球"
# hhad pick label.
_HHAD_LABELS: dict[str, str] = {"home": "让胜", "draw": "让平", "away": "让负"}


def _crs_pick_label(key: str) -> str:
    """Display label for a raw crs key: ``s02s01`` → ``2:1``, ``s1sh`` → 胜其他."""
    if key in _CRS_OTHER_LABELS:
        return _CRS_OTHER_LABELS[key]
    return f"{int(key[1:3])}:{int(key[4:6])}"


def _market_outcomes(match: BoldMatch, market: str) -> dict[str, float]:
    """The 体彩 decimal odds for ``market`` — keyed by that market's outcome keys.

    had/hhad → home/draw/away; ttg → total_0..total_7; crs → raw sHHsAA / s1sX
    keys (the ``...f`` flag keys are already excluded by the loader)."""
    if market == "had":
        return match.tc_odds
    if market == "hhad":
        return match.hhad_odds
    if market == "ttg":
        return match.ttg_odds
    return match.crs_odds


def _generic_contrarian(fair: dict[str, float], keys: list[str]) -> dict[str, float]:
    """Contrarian/长尾 score for an arbitrary keyspace — ``1 - fair`` for every
    non-favorite outcome, ``0.0`` for the 体彩 favorite (argmax of ``fair``)."""
    if not fair:
        return {k: 0.0 for k in keys}
    favorite = max(keys, key=lambda k: fair.get(k, 0.0))
    return {
        k: 0.0 if k == favorite else _clip01(1.0 - fair.get(k, 0.0)) for k in keys
    }


def _crs_internal_conflict(match: BoldMatch) -> dict[str, float]:
    """crs market's own internal conflict — each scoreline inherits the larger
    of its had-bucket and ttg-bucket internal conflict (spec §3).
    """
    keys = list(match.crs_odds)
    if not keys:
        return {}
    had_conflict = internal_conflict(match, "had")
    ttg_conflict = internal_conflict(match, "ttg")
    result: dict[str, float] = {}
    for key in keys:
        if key in _CRS_OTHER_LABELS:           # 其他 bucket — had sign only
            had_key = {"s1sh": "home", "s1sd": "draw", "s1sa": "away"}[key]
            result[key] = had_conflict.get(had_key, 0.0)
            continue
        home_goals, away_goals = int(key[1:3]), int(key[4:6])
        had_key = (
            "home" if home_goals > away_goals
            else "draw" if home_goals == away_goals
            else "away"
        )
        ttg_key = f"total_{min(home_goals + away_goals, 7)}"
        result[key] = max(
            had_conflict.get(had_key, 0.0), ttg_conflict.get(ttg_key, 0.0)
        )
    return result


def _market_signal_scores(
    match: BoldMatch, market: str
) -> tuple[dict[str, dict[str, float]], float]:
    """Return ``(per_outcome_signals, heat)`` for ``market``.

    ``per_outcome_signals`` maps signal name → {outcome_key: score}; ``heat`` is
    the per-match scalar. Only the signals active for ``market`` are populated.
    """
    outcomes = _market_outcomes(match, market)
    keys = list(outcomes)
    fair = _devig_map(outcomes)
    active = MARKET_SIGNALS[market]
    signals: dict[str, dict[str, float]] = {}

    if "conflict" in active:
        if market == "had":
            signals["conflict"] = conflict_score(fair, _fair_from_odds(match.euro_odds))
        elif market == "crs":
            signals["conflict"] = _crs_internal_conflict(match)
        elif market == "ttg":
            internal = internal_conflict(match, "ttg")
            external = external_conflict_ttg(match)
            signals["conflict"] = {
                o: _clip01(internal.get(o, 0.0) + external) for o in keys
            }
        else:  # hhad
            signals["conflict"] = internal_conflict(match, "hhad")
    if "contrarian" in active:
        signals["contrarian"] = _generic_contrarian(fair, keys)
    if "drift" in active:
        signals["drift"] = drift_score(match.euro_opening, match.euro_odds)
    if "dispersion" in active:
        if market == "had":
            signals["dispersion"] = dispersion_score(match.per_book_odds)
        else:  # ttg — dispersion from the 国际大小球 books, one scalar
            ou_disp = dispersion_score(match.ou_per_book)
            scalar = max(ou_disp.values(), default=0.0)
            signals["dispersion"] = {o: scalar for o in keys}
    heat = heat_score(match.tags, match.vig)
    return signals, heat


def market_boldness(match: BoldMatch, market: str) -> dict[str, float]:
    """Per-outcome boldness for one ``market`` — the active signals composed
    with per-market weight normalization (spec §3 跨市场可比性).

    The active-signal weights are renormalized to sum 1, so had (5 signals) and
    crs (3 signals) produce same-scale scores and the candidate pool is not
    structurally dominated by had.
    """
    signals, heat = _market_signal_scores(match, market)
    keys = list(_market_outcomes(match, market))
    active = MARKET_SIGNALS[market]
    weight_total = sum(_SIGNAL_WEIGHTS[s] for s in active)
    if weight_total <= 0 or not keys:
        return {k: 0.0 for k in keys}
    scores: dict[str, float] = {}
    for key in keys:
        total = 0.0
        for signal in active:
            weight = _SIGNAL_WEIGHTS[signal] / weight_total
            value = heat if signal == "heat" else signals.get(signal, {}).get(key, 0.0)
            total += weight * value
        scores[key] = total
    return scores


def _market_pick_label(market: str, key: str) -> str:
    """Display label for an outcome ``key`` in ``market``."""
    if market == "crs":
        return _crs_pick_label(key)
    if market == "ttg":
        return _TTG_LABELS.get(key, key)
    if market == "hhad":
        return _HHAD_LABELS.get(key, key)
    return OUTCOME_LABELS.get(key, key)


def bold_leg_for_market(match: BoldMatch, market: str) -> BoldLeg | None:
    """Pick the boldest outcome for ``match`` in one ``market``.

    Returns ``None`` when the match has no 体彩 odds for that market (graceful
    degradation — that market simply contributes no leg).
    """
    outcomes = _market_outcomes(match, market)
    usable = {k: v for k, v in outcomes.items() if v and v > 1.0}
    if not usable:
        return None
    scores = market_boldness(match, market)
    # spec §13 — pick the boldest leg whose 体彩 odds sit in the realistic
    # underdog range (a clear cold pick, not a freak scoreline). Only when NO
    # outcome is realistic does it fall back to all usable outcomes.
    realistic = {
        k: v for k, v in usable.items() if LEG_ODDS_MIN <= v <= LEG_ODDS_MAX
    }
    pick_pool = realistic or usable
    pick = max(pick_pool, key=lambda k: scores.get(k, 0.0))
    label = _market_pick_label(market, pick)
    reason = f"{MARKET_LABELS[market]} · {label} · 大胆腿"
    return BoldLeg(
        match_no=match.match_no,
        league=match.league,
        home=match.home,
        away=match.away,
        pick=pick,
        tc_odds=usable[pick],
        boldness=scores.get(pick, 0.0),
        reason=reason,
        market=market,
        pick_label=label,
    )


def candidate_legs(matches: list[BoldMatch]) -> list[BoldLeg]:
    """Build the cross-market candidate-leg pool.

    For each match, one bold leg per market it has 体彩 odds for; only the
    ``MAX_LEGS_PER_MATCH`` boldest are kept per match so the Rule-O combo
    generator always has cross-match options. The list is sorted by boldness.
    """
    legs: list[BoldLeg] = []
    for match in matches:
        per_match = [
            leg
            for market in MARKETS
            if (leg := bold_leg_for_market(match, market)) is not None
        ]
        per_match.sort(key=lambda lg: lg.boldness, reverse=True)
        legs.extend(per_match[:MAX_LEGS_PER_MATCH])
    legs.sort(key=lambda lg: lg.boldness, reverse=True)
    return legs


# ---------------------------------------------------------------------------
# Task 4 — day-level chaos value (spec §3.5)
# ---------------------------------------------------------------------------

# CHAOS_SCALE maps a per-match uncertainty (mean dispersion + mean conflict,
# roughly [0, 2]) onto the 0-100 chaos scale. Documented default.
CHAOS_SCALE: float = 50.0
# The candidate-pool size bounds — documented defaults (spec / plan §4).
POOL_MIN: int = 4
POOL_MAX: int = 10
# A match may put at most this many legs (its boldest markets) into the
# candidate pool — keeps cross-match options for the Rule-O combo generator.
MAX_LEGS_PER_MATCH: int = 2


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


# ---------------------------------------------------------------------------
# Task 5 — combination generation + 稳健底仓 (spec §4, §5)
# ---------------------------------------------------------------------------

# How many ranked tickets the bold output carries — documented default.
BOLD_TICKET_COUNT: int = 5
# The anchor ticket's leg count cap — a short 2-3 leg 稳健底仓 (spec §5).
ANCHOR_MAX_LEGS: int = 3

# 竞彩 single-ticket (一张彩票) payout cap — 返奖封顶, 500 万元 (spec §10.1,
# user-confirmed; a named, tunable constant).
JCZQ_PAYOUT_CAP_YUAN: float = 5_000_000.0
# Reference stake — 竞彩 base is 2 元/注; payout = stake × total_odds. Combined
# odds beyond JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN pay nothing extra.
REFERENCE_STAKE_YUAN: float = 2.0
# A bold ticket may use at most this many legs from one market (spec §10.2) —
# forces cross-market mix. Enforced ONLY when the candidate pool spans ≥2
# markets (a single-market day would otherwise have every ticket filtered out).
MAX_LEGS_PER_MARKET_PER_TICKET: int = 2
# Diversity penalty for cross-ticket concentration (spec §11.2) — a combo's
# rank score is divided by ``1 + CONCENTRATION_PENALTY × (reuse count)`` so
# ticket selection spreads across matches when the pool allows.
CONCENTRATION_PENALTY: float = 0.35
# A match appearing in more than this fraction of the bold tickets triggers the
# 🟦 cross-ticket concentration warning in the renderer (spec §11.2).
CONCENTRATION_WARN_FRACTION: float = 0.6

# spec §13 — bold tickets target a realistic combined-odds band rather than the
# maximum. The band is for a 3-fold; longer parlays scale it geometrically.
TARGET_ODDS_3FOLD_LOW: float = 80.0
TARGET_ODDS_3FOLD_HIGH: float = 400.0
# A bold leg's 体彩 odds are kept in this realistic underdog range — a clear
# cold pick, not a freak scoreline (spec §13).
LEG_ODDS_MIN: float = 3.0
LEG_ODDS_MAX: float = 9.0


def _effective_odds(total_odds: float) -> float:
    """Combined odds capped at the 竞彩 payout limit (spec §10.1).

    Real combined odds beyond ``JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN``
    pay nothing extra — the engine ranks combos by this capped value so it
    stops chasing un-collectable million-fold parlays. The ticket's stored
    ``total_odds`` keeps the true (uncapped) product; only ranking uses this.
    """
    return min(total_odds, JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN)


@dataclass(slots=True, frozen=True)
class BoldTicket:
    """A parlay ticket — a set of distinct-match legs + its combined odds.

    There is NO win-probability / EV field — the engine has no probabilities
    (spec §5). ``avg_boldness`` is a heuristic salience average, labelled
    "大胆分" in every renderer, NEVER "胜率 / 信心".
    """

    id: str
    kind: str
    legs: list[BoldLeg]
    fold: int
    total_odds: float
    avg_boldness: float
    note: str = ""


def _ticket_total_odds(legs: list[BoldLeg]) -> float:
    """Product of the legs' 体彩 odds — the parlay's combined decimal odds."""
    product = 1.0
    for leg in legs:
        product *= leg.tc_odds
    return product


def _ticket_avg_boldness(legs: list[BoldLeg]) -> float:
    """Mean boldness across a ticket's legs — a salience average, not a rate."""
    return sum(leg.boldness for leg in legs) / len(legs) if legs else 0.0


def _fold_weights(chaos: int) -> dict[int, int]:
    """How many tickets of each fold to keep, biased by the day chaos value.

    Calm days lean to short 3-folds; chaotic days lean to wild 4/5-folds —
    the §3.5 jitter rule, made concrete. Always returns a non-empty plan.
    """
    if chaos < 34:
        return {3: 3, 4: 1, 5: 1}
    if chaos <= 66:
        return {3: 2, 4: 2, 5: 1}
    return {3: 1, 4: 2, 5: 2}


def _band_fit(total_odds: float, fold: int) -> float:
    """How well a ticket's combined odds fits the realistic target band (spec §13).

    The 80-400× band for a 3-fold scales geometrically with ``fold`` (so per-leg
    odds stay realistic — a longer parlay is naturally higher). Returns 1.0
    inside the band and a ratio-based decay outside, so a moonshot combo ranks
    far below a realistic one.
    """
    exponent = fold / 3.0
    low = TARGET_ODDS_3FOLD_LOW**exponent
    high = TARGET_ODDS_3FOLD_HIGH**exponent
    if total_odds <= 0:
        return 0.0
    if total_odds < low:
        return total_odds / low
    if total_odds > high:
        return high / total_odds
    return 1.0


def _ticket_rank_score(legs: list[BoldLeg]) -> float:
    """A ticket's ranking score — ``band_fit × avg_boldness`` (spec §13).

    Ranks combos by how well they fit the realistic target odds band, NOT by
    raw odds — so the engine assembles bold-but-plausible parlays instead of
    chasing un-collectable million-fold moonshots.
    """
    return _band_fit(
        _ticket_total_odds(legs), len(legs)
    ) * _ticket_avg_boldness(legs)


def _over_cap_note(total_odds: float) -> str:
    """Honest cap annotation when a ticket's payout exceeds the 竞彩 limit, else ''."""
    cap_odds = JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN
    if total_odds <= cap_odds:
        return ""
    payout = total_odds * REFERENCE_STAKE_YUAN
    return (
        f" · ⚠️本票 {REFERENCE_STAKE_YUAN:g} 元理论赔付 {payout:,.0f} 元，"
        f"超竞彩 {JCZQ_PAYOUT_CAP_YUAN:,.0f} 元单票封顶 — 实际只兑至 "
        f"{JCZQ_PAYOUT_CAP_YUAN:,.0f} 元"
    )


def bold_combos(legs: list[BoldLeg], chaos: int) -> list[BoldTicket]:
    """Assemble creative cross-market 3/4/5-fold parlays from the candidate ``legs``.

    Each ticket's legs are distinct matches (Rule O). When the candidate pool
    spans ≥2 markets a ticket may use at most ``MAX_LEGS_PER_MARKET_PER_TICKET``
    legs from any one market (spec §10.2 — forces cross-market mix; skipped on a
    single-market pool so v1 had-only days still produce tickets). Tickets rank
    by ``effective_odds × avg_boldness`` (spec §10.1 — odds capped at the 竞彩
    payout limit). The fold mix is biased by ``chaos`` (§3.5). Fewer than 3
    candidate legs → no 3-fold is possible → an empty list (never a crash).
    """
    if len(legs) < 3:
        return []

    # The per-ticket market cap only makes sense — and is only safe — when the
    # pool actually has ≥2 markets to mix (spec §10.2).
    enforce_market_cap = len({lg.market for lg in legs}) >= 2

    fold_plan = _fold_weights(chaos)
    # spec §11.2 — running count of how many chosen tickets each match is in,
    # shared across all folds so 3/4/5-folds diversify against each other.
    appearance: Counter[str] = Counter()
    selected: list[list[BoldLeg]] = []
    for fold in (3, 4, 5):
        want = fold_plan.get(fold, 0)
        if want <= 0 or fold > len(legs):
            continue
        combos: list[tuple[float, list[BoldLeg]]] = []
        for combo in itertools.combinations(legs, fold):
            combo_legs = list(combo)
            # Rule O — one leg per match (distinct match_no makes the parlay
            # legal regardless of which markets the legs come from).
            if len({lg.match_no for lg in combo_legs}) != fold:
                continue
            # spec §10.2 — no single market may dominate a ticket.
            if enforce_market_cap:
                market_counts = Counter(lg.market for lg in combo_legs)
                if max(market_counts.values()) > MAX_LEGS_PER_MARKET_PER_TICKET:
                    continue
            combos.append((_ticket_rank_score(combo_legs), combo_legs))
        # spec §11.2 — diversity-penalized greedy: a combo's rank score is
        # divided by a penalty growing with how often its matches already
        # appear in chosen tickets, so the ticket set spreads across matches.
        # On a thin pool every candidate is penalized alike → degrades to plain
        # rank order (thin days still produce tickets).
        for _ in range(want):
            if not combos:
                break
            pick = max(
                range(len(combos)),
                key=lambda i: combos[i][0]
                / (
                    1.0
                    + CONCENTRATION_PENALTY
                    * sum(appearance[lg.match_no] for lg in combos[i][1])
                ),
            )
            _score, combo_legs = combos.pop(pick)
            selected.append(combo_legs)
            for leg in combo_legs:
                appearance[leg.match_no] += 1

    tickets: list[BoldTicket] = []
    for index, combo_legs in enumerate(
        sorted(selected, key=_ticket_rank_score, reverse=True),
        start=1,
    ):
        total_odds = _ticket_total_odds(combo_legs)
        note = "娱乐串 · 大胆分越高仅代表盘面越「有戏可挖」，不是命中概率"
        note += _over_cap_note(total_odds)
        tickets.append(
            BoldTicket(
                id=f"大胆票{index}",
                kind="大胆票",
                legs=combo_legs,
                fold=len(combo_legs),
                total_odds=round(total_odds, 4),
                avg_boldness=round(_ticket_avg_boldness(combo_legs), 4),
                note=note,
            )
        )
    return tickets


def anchor_ticket(matches: list[BoldMatch]) -> BoldTicket:
    """Build the 稳健底仓 — a short 2-3 leg parlay on the strongest 体彩 hot
    favorites (lowest-odds outcome per match).

    It is the hedge ballast for the bold tickets — NOT a "safe" bet, NOT
    +EV: the ``note`` says so honestly. High implied-hit-rate favorites still
    sit inside the same ~13% 竞彩 cut.
    """
    rated: list[tuple[float, BoldMatch, str]] = []
    for match in matches:
        usable = {o: v for o in OUTCOMES if (v := match.tc_odds.get(o)) and v > 0}
        if not usable:
            continue
        favorite = min(usable, key=lambda o: usable[o])
        rated.append((usable[favorite], match, favorite))
    rated.sort(key=lambda item: item[0])

    fold = min(ANCHOR_MAX_LEGS, len(rated))
    legs: list[BoldLeg] = []
    for fav_odds, match, favorite in rated[:fold]:
        legs.append(
            BoldLeg(
                match_no=match.match_no,
                league=match.league,
                home=match.home,
                away=match.away,
                pick=favorite,
                tc_odds=fav_odds,
                boldness=0.0,
                reason=f"{OUTCOME_LABELS[favorite]}向 · 体彩最强热门（最低赔）",
                market="had",
                pick_label=OUTCOME_LABELS[favorite],
            )
        )
    return BoldTicket(
        id="稳健底仓",
        kind="稳健底仓",
        legs=legs,
        fold=len(legs),
        total_odds=round(_ticket_total_odds(legs), 4) if legs else 0.0,
        avg_boldness=0.0,
        note=(
            "高命中倾向 ≠ 长期赚钱 — 它同样在 13% 抽水内，"
            "是大胆票的对冲压舱，不是「安全」、也不是赚钱腿"
        ),
    )


# ---------------------------------------------------------------------------
# Task 6 — engine assembly + welded honest label (spec §0, §5, §7)
# ---------------------------------------------------------------------------

# The welded honest label. EXACT text — asserted by a test (spec §7). The
# "−" is U+2212 (a real minus sign). This string is the first thing in every
# output (stdout / file / PDF / bot) — it must never be edited away.
HARD_LABEL: str = "🎲 娱乐性质 · 非 edge · 长期约 −13% 抽水期望 · 仅用娱乐预算下注"


@dataclass(slots=True, frozen=True)
class BoldComboPlan:
    """The day's full bold-combo output — anchor + bold tickets + chaos value.

    ``label`` is always ``HARD_LABEL``. There is NO win-probability / EV field
    anywhere in this plan or its tickets — the engine has no probabilities.
    """

    run_date: str
    day_chaos: int
    chaos_band: str
    anchor: BoldTicket
    tickets: list[BoldTicket]
    label: str = HARD_LABEL


# A market may fill at most this fraction of the candidate pool (spec §12) —
# guarantees the pool spans ≥2 markets when ≥2 markets exist, so the §10.2
# per-ticket market cap actually engages.
MARKET_POOL_SHARE: float = 0.5


def _balanced_pool(matches: list[BoldMatch], pool_n: int) -> list[BoldLeg]:
    """Build a match- AND market-balanced candidate pool of up to ``pool_n`` legs.

    比分 legs structurally dominate boldness (cold scorelines score ~1.0 on the
    contrarian/long-tail signal), so a plain boldness pool fills with 比分 and
    defeats the §10.2 per-ticket market cap. This builder caps any one market at
    ``pool_n * MARKET_POOL_SHARE`` slots: pass 1 seeds one leg per match (its
    boldest leg whose market is not yet full — match coverage + market
    coverage), pass 2 fills remaining slots by global boldness (still
    market-capped). A genuinely single-market day degrades to a single-market
    pool via the pass-1 fallback and §10.2 simply does not engage. The result
    is boldness-sorted.
    """
    per_match: list[list[BoldLeg]] = []
    for match in matches:
        legs = sorted(
            (
                leg
                for market in MARKETS
                if (leg := bold_leg_for_market(match, market)) is not None
            ),
            key=lambda lg: lg.boldness,
            reverse=True,
        )
        if legs:
            per_match.append(legs)
    if not per_match:
        return []

    # boldest matches first — they get first pick of the scarce market slots.
    per_match.sort(key=lambda legs: legs[0].boldness, reverse=True)
    market_cap = max(1, int(pool_n * MARKET_POOL_SHARE))
    pool: list[BoldLeg] = []
    market_count: Counter[str] = Counter()

    # pass 1 — one leg per match, preferring a market that is not yet full.
    for legs in per_match:
        if len(pool) >= pool_n:
            break
        choice = next(
            (lg for lg in legs if market_count[lg.market] < market_cap),
            legs[0],
        )
        pool.append(choice)
        market_count[choice.market] += 1

    # pass 2 — fill remaining slots with the next-boldest legs, market-capped.
    if len(pool) < pool_n:
        used = {id(lg) for lg in pool}
        rest = sorted(
            (lg for legs in per_match for lg in legs if id(lg) not in used),
            key=lambda lg: lg.boldness,
            reverse=True,
        )
        for leg in rest:
            if len(pool) >= pool_n:
                break
            if market_count[leg.market] < market_cap:
                pool.append(leg)
                market_count[leg.market] += 1

    pool.sort(key=lambda lg: lg.boldness, reverse=True)
    return pool


class BoldComboEngine:
    """Orchestrates the bold-combo pipeline (Tasks 2-5) into a ``BoldComboPlan``.

    per-match boldness → one bold leg per match → day chaos value → a
    chaos-sized candidate pool of the top-N bold legs → ranked 3/4/5-fold bold
    tickets + a 稳健底仓 anchor. No predictive model is touched.
    """

    def generate(self, run_date: str, matches: list[BoldMatch]) -> BoldComboPlan:
        """Build the day's plan from the supplied 体彩+国际 ``matches``."""
        chaos = day_chaos(matches)
        band = chaos_band(chaos)

        pool_n = chaos_pool_size(chaos)
        # spec §12 — a market-balanced pool: caps any one market at half the
        # slots so 比分 cannot fill the pool and defeat the §10.2 per-ticket
        # market cap. Also seeds one leg per match for Rule-O reachability.
        candidate_pool = _balanced_pool(matches, pool_n)

        tickets = bold_combos(candidate_pool, chaos)
        anchor = anchor_ticket(matches)

        return BoldComboPlan(
            run_date=run_date,
            day_chaos=chaos,
            chaos_band=band,
            anchor=anchor,
            tickets=tickets,
        )


def _render_leg(leg: BoldLeg) -> str:
    """One bold leg as a markdown bullet: 编号 / 市场 / 选项 / 体彩赔率 / 理由."""
    label = leg.pick_label or OUTCOME_LABELS.get(leg.pick, leg.pick)
    market = MARKET_LABELS.get(leg.market, leg.market)
    return (
        f"  - {leg.match_no} {leg.home} vs {leg.away} ｜ [{market}] "
        f"选 **{label}** @ {leg.tc_odds:.2f} ｜ {leg.reason}"
    )


def _render_ticket(ticket: BoldTicket) -> list[str]:
    """One ticket as markdown lines — odds + 大胆分, never a probability/EV."""
    lines = [
        f"### {ticket.id}（{ticket.fold}串1 · 合计赔率 {ticket.total_odds:.2f}"
    ]
    if ticket.kind == "大胆票":
        lines[0] += f" · 平均大胆分 {ticket.avg_boldness:.3f}）"
    else:
        lines[0] += "）"
    for leg in ticket.legs:
        lines.append(_render_leg(leg))
    if ticket.note:
        lines.append(f"  > {ticket.note}")
    return lines


def _concentration_warning(tickets: list[BoldTicket]) -> str:
    """A 🟦 note when one match dominates the bold tickets (spec §11.2).

    Returns '' unless ≥2 tickets exist and some match appears in more than
    ``CONCENTRATION_WARN_FRACTION`` of them — surfaced honestly so the user
    sees the tickets are NOT really diversified (they win/lose together).
    """
    if len(tickets) < 2:
        return ""
    appearance: Counter[str] = Counter()
    for ticket in tickets:
        for match_no in {lg.match_no for lg in ticket.legs}:
            appearance[match_no] += 1
    hot = [
        (m, c)
        for m, c in appearance.items()
        if c > CONCENTRATION_WARN_FRACTION * len(tickets)
    ]
    if not hot:
        return ""
    names = "、".join(
        f"{m}（{c}/{len(tickets)} 张）"
        for m, c in sorted(hot, key=lambda item: -item[1])
    )
    return (
        f"🟦 集中度提示：{names} 出现在多数大胆票里 —— "
        "这些票会一起赢一起输，并非真正分散风险。"
    )


def render_bold_plan(plan: BoldComboPlan) -> str:
    """Render a ``BoldComboPlan`` to honest-labelled markdown.

    The output STARTS with ``HARD_LABEL`` and the day chaos line — welded at
    the top of every output (spec §5). It carries NO advantage wording
    (胜率 / edge / +EV / 正期望 / 推荐下注 / 重仓) and NO probability/EV column:
    the boldness number is labelled "大胆分" only.
    """
    lines: list[str] = [HARD_LABEL, ""]
    lines.append(
        f"**当天大盘面混乱值：{plan.day_chaos}/100（{plan.chaos_band}）** "
        f"· {plan.run_date}"
    )
    lines.append(
        "> 混乱值越高 = 盘面越吵、组合越长越野；它只是娱乐抖动旋钮，不是优势信号。"
    )
    concentration = _concentration_warning(plan.tickets)
    if concentration:
        lines.append(concentration)
    lines.append("")

    lines.append("## 稳健底仓（对冲压舱）")
    if plan.anchor.legs:
        lines.extend(_render_ticket(plan.anchor))
    else:
        lines.append("  - （当天无可用 体彩 赔率，底仓略过）")
    lines.append("")

    lines.append("## 大胆票")
    if plan.tickets:
        for ticket in plan.tickets:
            lines.extend(_render_ticket(ticket))
            lines.append("")
    else:
        lines.append("  - （候选腿不足 3 条，今天不出大胆串）")
        lines.append("")

    lines.append(
        "_「大胆分」是盘面启发式显著性分，不是命中概率；本引擎不预测胜负、"
        "长期为负，仅供娱乐。注金请只用娱乐预算的小额。_"
    )
    lines.append(
        "_注金提示：上面多张票相互独立 ≠ 风险分散 —— 它们常共享同几场、"
        "会一起赢一起输。你完全可以只挑一张、或一张都不买。_"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Task 7 — context.json → BoldMatch loader (体彩 odds + optional 欧赔)
# ---------------------------------------------------------------------------

# 体彩 had 选项 → the engine's OUTCOMES vocabulary.
_HAD_PICK_TO_OUTCOME: dict[str, str] = {"胜": "home", "平": "draw", "负": "away"}

# A context.json match's ``role`` string → the heat tag it reads as.
_ROLE_TO_TAG: dict[str, str] = {"强胆场": "强胆场"}


def _had_odds(candidates: list[dict]) -> dict[str, float]:
    """Pull the 胜平负 (had) decimal odds out of a context.json match's
    ``candidates`` list. Returns an empty dict when the had pool is absent."""
    odds: dict[str, float] = {}
    for cand in candidates:
        if cand.get("pool") != "had":
            continue
        outcome = _HAD_PICK_TO_OUTCOME.get(str(cand.get("pick", "")))
        value = cand.get("odds")
        if outcome and isinstance(value, int | float) and value > 1.0:
            odds[outcome] = float(value)
    return odds


def _tc_vig(odds: dict[str, float]) -> float:
    """The 体彩 over-round (vig) of a 胜平负 line — ``sum(1/odds) - 1``."""
    if len(odds) < 3:
        return 0.12
    return sum(1.0 / v for v in odds.values()) - 1.0


def _match_tags(role: str) -> set[str]:
    """Map a context.json ``role`` to the engine's heat tags."""
    tag = _ROLE_TO_TAG.get(role.strip())
    return {tag} if tag else set()


def bold_matches_from_context(
    context: dict, *, euro_by_match_no: dict[str, dict]
) -> list[BoldMatch]:
    """Build ``BoldMatch`` objects from a daily ``context.json`` + optional 欧赔.

    Each context match must carry a 胜平负 (``had``) pool — that is the only
    market the engine scores. ``euro_by_match_no`` maps 竞彩号 →
    ``{"odds": .., "opening": .., "per_book": ..}`` (the 欧赔 collected from
    500.com); a match absent from it simply gets empty 欧赔 fields, and its
    conflict/drift/dispersion signals degrade to 0 — heat + contrarian still
    work. A match with no usable ``had`` odds is skipped (never a crash).
    """
    matches: list[BoldMatch] = []
    for raw in context.get("matches") or []:
        tc_odds = _had_odds(raw.get("candidates") or [])
        if len(tc_odds) < 3:
            continue
        euro = euro_by_match_no.get(str(raw.get("match_no", "")), {})
        matches.append(
            BoldMatch(
                match_no=str(raw.get("match_no", "")),
                league=str(raw.get("league", "")),
                home=str(raw.get("home_team", "")),
                away=str(raw.get("away_team", "")),
                tc_odds=tc_odds,
                euro_odds=dict(euro.get("odds") or {}),
                euro_opening=dict(euro.get("opening") or {}),
                per_book_odds={
                    k: list(v) for k, v in (euro.get("per_book") or {}).items()
                },
                tags=_match_tags(str(raw.get("role", ""))),
                vig=_tc_vig(tc_odds),
            )
        )
    return matches


def euro_from_fcom500(collected: dict) -> dict[str, dict]:
    """Reshape a ``Fcom500OddsProvider.collect()`` result into the
    ``euro_by_match_no`` mapping ``bold_matches_from_context`` expects.

    Only the 胜平负 (``match_winner``) market is used — its parsed
    ``MarketOdds`` carries ``opening_odds`` + ``per_book_odds`` (Task 1).
    A match whose 欧赔 page failed to parse simply has no entry — graceful
    degradation. This reads the 500.com domain objects but imports NO
    predictive model.
    """
    euro: dict[str, dict] = {}
    for match_no, entry in collected.items():
        market = entry.odds.markets.get("match_winner")
        if market is None:
            continue
        odds = {o.outcome_key: o.average_odds for o in market.outcomes}
        euro[match_no] = {"odds": odds}
    return euro


def _f(value: object) -> float | None:
    """Parse a Sporttery odds string to float; ``None`` when unusable.

    Odds are always positive, so a non-positive parse is treated as unusable.
    """
    result = _signed_float(value)
    return result if result is not None and result > 0 else None


def _signed_float(value: object) -> float | None:
    """Parse a Sporttery numeric string to float, keeping its sign.

    Unlike ``_f`` this accepts negatives — the 让球 ``goalLine`` is legitimately
    negative when the home side gives goals (e.g. ``"-1"``). ``None`` when the
    value cannot be parsed at all (an absent / non-numeric field).
    """
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _had_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery had/hhad pool ``{h,d,a}`` → ``{home,draw,away}`` odds."""
    out: dict[str, float] = {}
    for src, dst in (("h", "home"), ("d", "draw"), ("a", "away")):
        value = _f(pool.get(src))
        if value is not None:
            out[dst] = value
    return out


def _ttg_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery ttg pool ``{s0..s7}`` → ``{total_0..total_7}`` odds."""
    out: dict[str, float] = {}
    for k in range(8):
        value = _f(pool.get(f"s{k}"))
        if value is not None:
            out[f"total_{k}"] = value
    return out


def _crs_from_pool(pool: dict) -> dict[str, float]:
    """Sporttery crs pool → ``{raw_key: odds}`` — the ``...f`` flag keys and any
    metadata keys (``goalLine`` …) are excluded; only ``sHHsAA`` / ``s1sX``."""
    out: dict[str, float] = {}
    for key, raw in pool.items():
        if not (_RE_CRS_KEY.match(key)):
            continue
        value = _f(raw)
        if value is not None:
            out[key] = value
    return out


def _strong_favorite_tags(had_odds: dict[str, float]) -> set[str]:
    """A 强胆场 heat tag when the 体彩 had favorite is priced ≤ 1.35."""
    usable = [v for v in had_odds.values() if v and v > 0]
    return {"强胆场"} if usable and min(usable) <= 1.35 else set()


def bold_matches_from_sporttery(
    value: dict, *, run_date: str, bold_odds: dict[str, dict]
) -> list[BoldMatch]:
    """Build ``BoldMatch`` objects from a Sporttery ``getMatchCalculatorV1``
    response + the ``collect_bold_odds`` result.

    ``value`` is the API ``value`` dict (``matchInfoList`` → ``subMatchList``);
    only ``Selling`` matches whose ``businessDate`` equals ``run_date`` are
    kept. ``bold_odds`` maps 竞彩号 → ``{"match_winner": MarketOdds,
    "over_under": MarketOdds}`` — a match absent from it gets empty 国际 fields
    and its 欧赔/大小球 signals degrade to 0. A match is loaded when ANY of its
    four markets has usable odds (spec §11.1 — 让球/总进球/比分 do not need
    胜平负); a match with every pool empty is skipped (never a crash).
    """
    matches: list[BoldMatch] = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(raw.get("businessDate") or day.get("businessDate") or "")
            if run_date and business_date and business_date != run_date:
                continue
            hhad_pool = raw.get("hhad") or {}
            had_odds = _had_from_pool(raw.get("had") or {})
            hhad_odds = _had_from_pool(hhad_pool)
            ttg_odds = _ttg_from_pool(raw.get("ttg") or {})
            crs_odds = _crs_from_pool(raw.get("crs") or {})
            # spec §11.1 — load the match if ANY market has usable odds. had
            # missing → no 胜平负 leg, no anchor slot (anchor is had-only and
            # skips it), but 让球/总进球/比分 legs are produced as normal.
            if not (
                len(had_odds) >= 3 or len(hhad_odds) >= 3 or ttg_odds or crs_odds
            ):
                continue
            match_no = str(raw.get("matchNumStr") or "")
            euro = (bold_odds.get(match_no) or {}).get("match_winner")
            over_under = (bold_odds.get(match_no) or {}).get("over_under")
            matches.append(
                BoldMatch(
                    match_no=match_no,
                    league=str(raw.get("leagueAbbName") or ""),
                    home=str(raw.get("homeTeamAbbName") or ""),
                    away=str(raw.get("awayTeamAbbName") or ""),
                    tc_odds=had_odds,
                    euro_odds=dict(euro.odds) if euro else {},
                    euro_opening=dict(euro.opening_odds) if euro else {},
                    per_book_odds=(
                        {k: list(v) for k, v in euro.per_book_odds.items()}
                        if euro else {}
                    ),
                    tags=_strong_favorite_tags(had_odds),
                    vig=_tc_vig(had_odds),
                    hhad_odds=hhad_odds,
                    hhad_line=_signed_float(hhad_pool.get("goalLineValue"))
                    or _signed_float(hhad_pool.get("goalLine")) or 0.0,
                    ttg_odds=ttg_odds,
                    crs_odds=crs_odds,
                    ou_odds=dict(over_under.odds) if over_under else {},
                    ou_line=float(over_under.line)
                    if over_under and over_under.line else 0.0,
                    ou_per_book=(
                        {k: list(v) for k, v in over_under.per_book_odds.items()}
                        if over_under else {}
                    ),
                )
            )
    return matches


def persist_sporttery_snapshot(run_date: str, output_dir, value: dict) -> None:
    """Write the Sporttery response to ``<output_dir>/daily/<run_date>/
    sporttery_markets.json`` so ``--replay`` is reproducible."""
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def load_sporttery_snapshot(run_date: str, output_dir) -> dict | None:
    """Read a persisted Sporttery snapshot; ``None`` when absent."""
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def replay_bold_combos(run_date: str, output_dir) -> str:
    """Replay a stored ``context.json`` through the bold-combo engine.

    Reads ``<output_dir>/daily/<run_date>/context.json`` for the 体彩 odds,
    attempts to enrich it with 500.com 欧赔 (degrading silently to 体彩-only on
    any failure), runs ``BoldComboEngine`` and returns the honest-labelled
    markdown. Raises ``FileNotFoundError`` when the context file is absent.
    """
    import json
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)
    ctx_path = Path(output_dir) / "daily" / run_date / "context.json"
    if not ctx_path.exists():
        raise FileNotFoundError(f"context.json not found: {ctx_path}")
    context = json.loads(ctx_path.read_text(encoding="utf-8"))

    euro_by_match_no: dict[str, dict] = {}
    try:
        from nutmeg.data.fcom500 import Fcom500Client, Fcom500OddsProvider

        with Fcom500Client() as client:
            collected = Fcom500OddsProvider(client=client).collect(run_date)
        euro_by_match_no = euro_from_fcom500(collected)
    except Exception:  # noqa: BLE001 — 欧赔 is optional; degrade to 体彩-only
        logger.warning("bold-combos: 欧赔 enrichment failed — 体彩-only", exc_info=True)

    matches = bold_matches_from_context(
        context, euro_by_match_no=euro_by_match_no
    )
    plan = BoldComboEngine().generate(run_date, matches)
    return render_bold_plan(plan)


def run_bold_combos_multimarket(
    run_date: str,
    output_dir,
    *,
    replay: bool,
) -> str:
    """Run the multi-market bold engine for ``run_date``.

    ``replay=True``: read the persisted Sporttery snapshot (degrade to the v1
    context.json had-only path when absent). ``replay=False``: fetch the
    Sporttery full market live, persist the snapshot, enrich with 500.com 国际
    odds. Returns the honest-labelled markdown.
    """
    import logging

    logger = logging.getLogger(__name__)

    value: dict | None = None
    if replay:
        value = load_sporttery_snapshot(run_date, output_dir)
        if value is None:
            logger.warning(
                "bold-combos: no snapshot for %s — falling back to v1 context.json",
                run_date,
            )
            return replay_bold_combos(run_date, output_dir)
    else:
        from nutmeg.services.jczq import SportteryJczqCalculatorProvider

        fetched = SportteryJczqCalculatorProvider().fetch()
        value = fetched.get("value") if "value" in fetched else fetched
        persist_sporttery_snapshot(run_date, output_dir, value)

    bold_odds: dict[str, dict] = {}
    if not replay:
        try:
            from nutmeg.data.fcom500 import Fcom500Client, collect_bold_odds

            with Fcom500Client() as client:
                bold_odds = collect_bold_odds(client)
        except Exception:  # noqa: BLE001 — 国际 odds optional; degrade
            logger.warning("bold-combos: 国际 odds enrichment failed", exc_info=True)

    matches = bold_matches_from_sporttery(
        value or {}, run_date=run_date, bold_odds=bold_odds
    )
    plan = BoldComboEngine().generate(run_date, matches)
    return render_bold_plan(plan)
