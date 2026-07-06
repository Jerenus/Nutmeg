"""市场数据内核 — bold_combos 的确定性底座(2026-07-06 从 jczq_bold_combos 抽出)。

类型 + 常量 + 体彩/欧赔盘口解析 + 去水 fair + 信号打分。**无 v1 组合 generator 逻辑**。
活引擎(jczq_tiered / jczq_today / worldcup)只依赖本内核,不再传递加载退役 generator。
抽取由 scripts 机械完成、行为保持不变;拆分依据见 docs/jczq-refactor-roadmap.md Tier R1。
"""
from __future__ import annotations

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

OUTCOMES: tuple[str, str, str] = ("home", "draw", "away")


MARKETS: tuple[str, ...] = ("had", "hhad", "ttg", "crs")


MARKET_SIGNALS: dict[str, tuple[str, ...]] = {
    "had": ("conflict", "contrarian", "drift", "dispersion", "heat"),
    "hhad": ("conflict", "contrarian", "heat"),
    "ttg": ("conflict", "contrarian", "dispersion", "heat"),
    "crs": ("conflict", "contrarian", "heat"),
}


MARKET_LABELS: dict[str, str] = {
    "had": "胜平负", "hhad": "让球", "ttg": "总进球", "crs": "比分",
}


_RE_CRS_KEY = re.compile(r"^s\d{2}s\d{2}$|^s1s[hda]$")


DRIFT_GAIN: float = 6.0


DISPERSION_GAIN: float = 12.0


HEAT_TAG: float = 0.25


HEAT_VIG_GAIN: float = 4.0


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


WEIGHT_CONFLICT: float = 0.2


WEIGHT_CONTRARIAN: float = 0.2


WEIGHT_DRIFT: float = 0.2


WEIGHT_DISPERSION: float = 0.2


WEIGHT_HEAT: float = 0.2


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
    # De-vigged 国际 fair probabilities for the 胜平负 market (home/draw/away).
    # Empty when the 欧赔 snapshot is missing → §17.1 gap guard degrades
    # gracefully (anchor falls back to v1 lowest-odds-favorite behaviour).
    euro_fair_prob: dict[str, float] = field(default_factory=dict)
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


_SIGNAL_WEIGHTS: dict[str, float] = {
    "conflict": WEIGHT_CONFLICT,
    "contrarian": WEIGHT_CONTRARIAN,
    "drift": WEIGHT_DRIFT,
    "dispersion": WEIGHT_DISPERSION,
    "heat": WEIGHT_HEAT,
}


_CRS_OTHER_LABELS: dict[str, str] = {"s1sh": "胜其他", "s1sd": "平其他", "s1sa": "负其他"}


_TTG_LABELS: dict[str, str] = {f"total_{k}": f"{k}球" for k in range(7)}


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


CHAOS_SCALE: float = 50.0


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


def chaos_band(chaos: int) -> str:
    """Label the day chaos value: 平静 (< 34) / 中等 (34-66) / 混乱 (> 66)."""
    if chaos < 34:
        return "平静"
    if chaos <= 66:
        return "中等"
    return "混乱"


ANCHOR_GAP_THRESHOLD: float = 0.08


LEG_ODDS_MIN: float = 3.0


LEG_ODDS_MAX: float = 9.0


THEME_DRAW: str = "平局收割"


THEME_SCORE: str = "冷门比分梦"


THEME_HANDICAP: str = "黑马让球"


THEME_GOALS: str = "进球狂欢"


THEME_MIXED: str = "全市场混搭"


MIN_THEME_LEGS_FOR_RETIREMENT: int = 30


@dataclass(slots=True, frozen=True)
class RetiredTheme:
    """spec §24 — one cumulative-history snapshot of a soft-retired theme.

    Captured at plan-build time so the renderer can print the exact 0/{tickets}
    + leg-count it acted on, even after the next day's history mutates the
    underlying file. ``ticket_hits`` is structurally 0 (retirement requires it).
    """

    theme: str
    tickets: int
    ticket_hits: int
    legs: int
    leg_hits: int


def retired_themes_with_stats(
    by_theme: dict[str, dict[str, int]] | None,
) -> tuple[RetiredTheme, ...]:
    """spec §24 — the renderer view of ``retired_themes_from_history``.

    Same gate (≥30 graded legs, 0 ticket_hits), but emits a snapshot tuple of
    ``RetiredTheme`` records sorted by ticket count desc — the biggest 0%
    underperformer shows first in the rendered notice. Empty/missing input →
    empty tuple, never a crash.
    """
    if not by_theme:
        return ()
    retired = [
        RetiredTheme(
            theme=theme,
            tickets=int(slot.get("tickets", 0)),
            ticket_hits=int(slot.get("ticket_hits", 0)),
            legs=int(slot.get("legs", 0)),
            leg_hits=int(slot.get("leg_hits", 0)),
        )
        for theme, slot in by_theme.items()
        if int(slot.get("legs", 0)) >= MIN_THEME_LEGS_FOR_RETIREMENT
        and int(slot.get("ticket_hits", 0)) == 0
    ]
    retired.sort(key=lambda r: r.tickets, reverse=True)
    return tuple(retired)


_MARKET_THEME: dict[str, str] = {
    "crs": THEME_SCORE, "hhad": THEME_HANDICAP, "ttg": THEME_GOALS,
}


_THEME_SCRIPTS: dict[str, str] = {
    THEME_DRAW: "赌多场打平 / 让平 —— 大众最不敢站的方向，冷热都收在这一张。",
    THEME_SCORE: "押的是几个具体比分画面 —— 盘面给的不是结果，是想象。",
    THEME_HANDICAP: "全靠让球盘撬动 —— 让分线才是体彩对强弱的真实态度。",
    THEME_GOALS: "赌进球数往两端走 —— 闷平和大爆发都收在这一张。",
    THEME_MIXED: "四个市场混着打 —— 盘面最吵、想象力最大的一张。",
}


def _is_draw_lean(leg: BoldLeg) -> bool:
    """True when a leg backs a draw-flavoured outcome — 胜平负平 / 让球让平 /
    比分平局 (an equal scoreline or the 平其他 ``s1sd`` bucket)."""
    if leg.market in ("had", "hhad"):
        return leg.pick == "draw"
    if leg.market == "crs":
        if leg.pick == "s1sd":
            return True
        key = leg.pick
        if len(key) == 6 and key[0] == "s" and key[3] == "s":
            return key[1:3] == key[4:6]
    return False


def ticket_theme(legs: list[BoldLeg]) -> tuple[str, str]:
    """Classify a bold ticket into a 剧本 archetype + its narrative line (spec §15).

    Descriptive, post-hoc — labels what the ticket already is, never changes
    leg selection. Priority: a draw-leaning majority → 平局收割; else a single
    market holding the majority of legs → that market's theme; else 全市场混搭.
    Empty legs → ``("", "")`` so the renderer simply omits the theme.
    """
    if not legs:
        return ("", "")
    fold = len(legs)
    draw_legs = sum(1 for lg in legs if _is_draw_lean(lg))
    if draw_legs * 2 > fold:
        theme = THEME_DRAW
    else:
        counts = Counter(lg.market for lg in legs)
        top_market, top_count = counts.most_common(1)[0]
        if top_count * 2 > fold and top_market in _MARKET_THEME:
            theme = _MARKET_THEME[top_market]
        else:
            theme = THEME_MIXED
    return (theme, _THEME_SCRIPTS[theme])


HARD_LABEL: str = "🎲 娱乐性质 · 非 edge · 长期约 −13% 抽水期望 · 仅用娱乐预算下注"


@dataclass(slots=True, frozen=True)
class MatchSignals:
    """spec §20-§22 — per-match implied signals harvested from the 体彩 board.

    All fields default to 0.0; a market that isn't quoted contributes 0 and
    downstream helpers treat 0.0 as "signal unavailable" and skip. No
    predictive-model fields here — purely de-vigged 体彩 implied probabilities.
    """

    min_had_odds: float = 0.0           # min decimal odds across had outcomes
    draw_implied: float = 0.0           # 1/had[draw] — 体彩-implied draw prob
    high_goals_implied: float = 0.0     # de-vigged Σ ttg buckets ≥ 3 goals
    underdog_let_implied: float = 0.0   # de-vigged hhad[draw]+hhad[away]


@dataclass(slots=True, frozen=True)
class PoolSignals:
    """spec §20-§22 — day pool aggregate signals computed once at generate time.

    Empty ``by_match`` (legacy callers or no matches) → every derived render
    helper returns ``""`` / ``[]`` so the plan still renders cleanly.
    """

    by_match: dict[str, MatchSignals] = field(default_factory=dict)
    match_count: int = 0


def _ttg_bucket_goals(key: str) -> int:
    """Parse the integer goal count from a ``total_k`` ttg-bucket key.

    ``total_7`` is the ≥7 over-bucket; callers using a goal-count threshold
    treat ≥7 the same as 7. Unknown keys → -1 (skipped by callers).
    """
    if not key.startswith("total_"):
        return -1
    try:
        return int(key.removeprefix("total_"))
    except ValueError:
        return -1


def compute_pool_signals(matches: list[BoldMatch]) -> PoolSignals:
    """spec §20-§22 — per-match implied signals harvested from 体彩 boards.

    For each match: min had odds (§20 consensus tilt), draw 体彩-implied prob
    (§21 平局收割 resonance), de-vigged P(ttg≥3) from the ttg board (§21
    进球狂欢 resonance), de-vigged hhad[draw]+hhad[away] (the underdog-let
    direction). Markets that aren't quoted contribute 0.0 — downstream
    helpers treat 0.0 as "signal unavailable" and skip.
    """
    by_match: dict[str, MatchSignals] = {}
    for match in matches:
        usable_had = [v for v in match.tc_odds.values() if v and v > 0]
        min_had = min(usable_had) if usable_had else 0.0
        draw_o = match.tc_odds.get("draw")
        draw_imp = 1.0 / draw_o if draw_o and draw_o > 0 else 0.0
        ttg_fair = _devig_map(match.ttg_odds)
        high_goals = sum(
            v for key, v in ttg_fair.items() if _ttg_bucket_goals(key) >= 3
        )
        hhad_fair = _devig_map(match.hhad_odds)
        underdog_let = hhad_fair.get("draw", 0.0) + hhad_fair.get("away", 0.0)
        by_match[match.match_no] = MatchSignals(
            min_had_odds=min_had,
            draw_implied=draw_imp,
            high_goals_implied=high_goals,
            underdog_let_implied=underdog_let,
        )
    return PoolSignals(by_match=by_match, match_count=len(matches))


def _tc_vig(odds: dict[str, float]) -> float:
    """The 体彩 over-round (vig) of a 胜平负 line — ``sum(1/odds) - 1``."""
    if len(odds) < 3:
        return 0.12
    return sum(1.0 / v for v in odds.values()) - 1.0


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
                    euro_fair_prob=dict(euro.fair_probability) if euro else {},
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


def load_sporttery_snapshot(run_date: str, output_dir) -> dict | None:
    """Read a persisted Sporttery snapshot; ``None`` when absent."""
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_bold_odds_snapshot(run_date: str, output_dir) -> dict:
    """Read a persisted 国际-odds snapshot back into the ``bold_odds`` shape
    ``bold_matches_from_sporttery`` expects — ``{竞彩号: {market: MarketOdds}}``.

    Absent snapshot → ``{}`` — pre-§14 dates (and any day the live 国际 fetch
    failed) degrade to 体彩-only exactly as before, never a crash. Rebuilds real
    ``MarketOdds`` objects (a plain fcom500 dataclass — imports NO predictive
    model).
    """
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "bold_odds.json"
    if not path.exists():
        return {}
    from nutmeg.data.fcom500 import MarketOdds

    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        match_no: {
            market: MarketOdds(**fields) for market, fields in markets.items()
        }
        for match_no, markets in raw.items()
    }



# ---------------------------------------------------------------------------
# 腿评分(2026-07-06 从 jczq_bold_review 抽入 — 纯确定性,活复盘路径 jczq_tiered_review
# 只需这一件,搬进内核后 review 路径彻底脱离 v1 bold_review/generator 簇)。
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class GradedLeg:
    """One bold leg graded against the actual result.

    ``hit`` is ``None`` when the match has no result yet (待定) — a pending leg
    never counts toward a hit rate's denominator (spec §16)."""

    match_no: str
    market: str
    pick_label: str
    tc_odds: float
    actual: str | None
    hit: bool | None


def grade_leg(leg: BoldLeg, results: dict[str, dict[str, str]]) -> GradedLeg:
    """Grade one leg — ``hit`` is ``actual == leg.pick_label`` (pick_label is the
    human form: 胜 / 让平 / 2球 / 2:1, matching okooo's winning-option string).

    No result for that match+market → ``actual=None``, ``hit=None`` (待定)."""
    actual = (results.get(leg.match_no) or {}).get(leg.market) or None
    hit = None if actual is None else (actual == leg.pick_label)
    return GradedLeg(
        match_no=leg.match_no,
        market=leg.market,
        pick_label=leg.pick_label,
        tc_odds=leg.tc_odds,
        actual=actual,
        hit=hit,
    )
