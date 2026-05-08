"""Analytics core for the JCZQ daily advisor.

Turns raw Sporttery legs into per-match analytics (vig-normalized implied
probabilities, EV gap vs baseline, popularity, drift signals, cluster flags) and
provides the scoring/bucket primitives used by the daily generator.

This module is deliberately data-source-agnostic: callers pass optional baseline
probability providers, popularity rankers, and drift signals so the same code
runs under unit tests (no network) and live (with all signals wired up).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from nutmeg.domain.jczq_daily import JczqDailyLeg, JczqDailyMatch

HAD_OUTCOMES = ("胜", "平", "负")

DEFAULT_LEAGUE_PRIORS: dict[str, tuple[float, float, float]] = {
    "英超": (0.46, 0.25, 0.29),
    "西甲": (0.46, 0.26, 0.28),
    "意甲": (0.45, 0.27, 0.28),
    "德甲": (0.45, 0.24, 0.31),
    "法甲": (0.46, 0.26, 0.28),
    "荷甲": (0.48, 0.23, 0.29),
    "葡超": (0.46, 0.26, 0.28),
    "苏超": (0.45, 0.26, 0.29),
    "比甲": (0.45, 0.27, 0.28),
    "挪超": (0.49, 0.24, 0.27),
    "瑞超": (0.46, 0.27, 0.27),
    "日职": (0.40, 0.29, 0.31),
    "韩K联": (0.42, 0.28, 0.30),
    "美职": (0.50, 0.23, 0.27),
    "巴甲": (0.50, 0.26, 0.24),
    "阿甲": (0.45, 0.30, 0.25),
    "欧冠": (0.42, 0.27, 0.31),
    "欧联": (0.43, 0.27, 0.30),
    "解放者杯": (0.47, 0.27, 0.26),
}
DEFAULT_PRIOR: tuple[float, float, float] = (0.43, 0.27, 0.30)

POOL_PROCESS = ("ttg", "hafu", "hhad")


class BaselineProvider(Protocol):
    """Returns prior (主胜/平/客胜) probability triple for a league."""

    def get(self, league: str) -> tuple[float, float, float]: ...


class PopularityProvider(Protocol):
    """Returns a popularity (score, tier) tuple for a match."""

    def get(self, match: JczqDailyMatch) -> tuple[int, str]: ...


class DriftProvider(Protocol):
    """Returns latest steam-style implied-prob deltas keyed by (pool, pick)."""

    def get(self, match_no: str) -> dict[tuple[str, str], float]: ...


@dataclass(frozen=True, slots=True)
class LeaguePriorBaseline:
    overrides: dict[str, tuple[float, float, float]] = field(default_factory=dict)

    def get(self, league: str) -> tuple[float, float, float]:
        if league in self.overrides:
            return self.overrides[league]
        return DEFAULT_LEAGUE_PRIORS.get(league, DEFAULT_PRIOR)


@dataclass(frozen=True, slots=True)
class MatchAnalytics:
    match_no: str
    league: str
    favorite_outcome: Literal["胜", "平", "负"] | None
    favorite_odds: float | None
    favorite_implied: float
    implied_probs: dict[str, float]
    vig_pct: float
    dispersion: float
    popularity_score: int
    popularity_tier: str
    baseline_probs: dict[str, float]
    ev_gaps: dict[str, dict[str, float]]
    is_strong_banker: bool
    is_comfort_risk: bool
    is_chaos: bool
    is_draw_friendly: bool
    is_upset_candidate: bool
    is_three_way_coinflip: bool = False
    is_high_volatility_league: bool = False
    is_late_kickoff: bool = False
    drift: dict[tuple[str, str], float] = field(default_factory=dict)


# Rule E: vig > 12.5% AND max(implied)-min(implied) < 10pp → had pool is a coin flip,
# unsuitable as a draw/cold-leverage leg in main/inspiration. hhad/ttg/crs survive.
COINFLIP_VIG_THRESHOLD = 0.125
COINFLIP_IMPLIED_SPREAD_THRESHOLD = 0.10

# Rule C: leagues whose recent ttg median ≥ this value are flagged as
# high-volatility — generator avoids low-side ttg picks (≤ 2球) there.
HIGH_VOLATILITY_TTG_MEDIAN = 2.7

# Rule R2 (5/08 落库): bootstrap high-volatility leagues for known high-goal-
# variance competitions. These trigger hi-vol behavior even before we
# accumulate enough oracle samples to compute a stable rolling median.
# Evidence from 5/07 review: 4 of 5 sold matches were 欧罗巴 / 解放者杯 / 沙职
# and averaged ≥ 3 goals; Rule C's sample-based path failed because
# `min_samples=4` had not been satisfied. Override fires regardless.
HIGH_VOL_LEAGUE_OVERRIDE: frozenset[str] = frozenset({
    "欧冠",
    "欧罗巴",
    "欧联",
    "解放者杯",
    "南美杯",
    "美职",
    "沙职",
    "巴甲",
    "阿甲",
})

# Rule N (R4, 5/08): late-kickoff matches (Beijing time hour ∈ [6, 12))
# carry settlement-delay risk — South American afternoon kickoffs in CONMEBOL
# competitions land 06:00-09:00 Beijing morning, often still pending at the
# next-day 08:00 launchd review window. 5/07 周四006 麦独立 vs 弗拉门戈
# (08:30 Beijing) was the canonical case. Generator caps main/inspiration
# exposure to ≤1 such leg per ticket.
LATE_KICKOFF_HOUR_START_BEIJING = 6
LATE_KICKOFF_HOUR_END_BEIJING = 12  # exclusive


def _is_late_kickoff(match_time: str) -> bool:
    """Parse 'HH:MM:SS' Beijing time → True if hour ∈ [start, end). Defensive
    against missing or malformed values; returns False on parse failure."""
    if not match_time:
        return False
    try:
        hour = int(match_time.split(":")[0])
    except (ValueError, IndexError):
        return False
    return LATE_KICKOFF_HOUR_START_BEIJING <= hour < LATE_KICKOFF_HOUR_END_BEIJING


# Rule J: extreme-ticket crs picks must clear at least this Poisson edge floor.
# 4-day backtest: crs hit 1/14 (7.1%); rejected legs were all edge ≤ -20%.
CRS_POISSON_EDGE_FLOOR = -0.10

# Rule I-1: high-odds had legs (≥ this odds) require Poisson edge ≥ 0.05 to be
# usable as a leverage leg (4-day backtest: had ≥ 5.0 hit 0/1).
HIGH_ODDS_HAD_THRESHOLD = 5.0
HIGH_ODDS_HAD_REQUIRED_EDGE = 0.05

# Rule I-2: contrarian intent must reject any leg the Poisson model strongly
# opposes (5/05's contrarian ttg 4球 had edge -22.5%).
CONTRARIAN_POISSON_REJECT_BELOW = -0.15


def compute_analytics(
    matches: Iterable[JczqDailyMatch],
    *,
    baseline: BaselineProvider | None = None,
    popularity: PopularityProvider | None = None,
    drift: DriftProvider | None = None,
    league_volatility: dict[str, float] | None = None,
) -> dict[str, MatchAnalytics]:
    """Build per-match analytics keyed by `match_no`.

    Pure function: deterministic given the same inputs, no I/O.
    """

    base = baseline or LeaguePriorBaseline()
    out: dict[str, MatchAnalytics] = {}
    for match in matches:
        had_legs = {leg.pick: leg.odds for leg in match.candidates if leg.pool == "had"}
        had_odds = {pick: had_legs[pick] for pick in HAD_OUTCOMES if pick in had_legs}
        if not had_odds:
            continue
        raw_implied = {pick: 1.0 / odd for pick, odd in had_odds.items() if odd > 0}
        gross = sum(raw_implied.values())
        vig = max(0.0, gross - 1.0)
        implied = {pick: raw_implied[pick] / gross for pick in raw_implied} if gross else {}
        favorite_pick, favorite_odds = (
            min(had_odds.items(), key=lambda item: item[1]) if had_odds else (None, None)
        )
        favorite_implied = implied.get(favorite_pick, 0.0) if favorite_pick else 0.0
        odds_values = list(had_odds.values())
        dispersion = _std(odds_values)

        baseline_triple = base.get(match.league)
        baseline_probs = {
            "胜": baseline_triple[0],
            "平": baseline_triple[1],
            "负": baseline_triple[2],
        }
        ev_gaps = _compute_ev_gaps(match, implied=implied, baseline=baseline_probs)

        pop_score, pop_tier = popularity.get(match) if popularity else (0, "normal")
        drift_entries = drift.get(match.match_no) if drift else {}

        is_strong = (favorite_odds is not None) and favorite_odds <= 1.35
        is_comfort = (
            favorite_odds is not None
            and 1.75 <= favorite_odds <= 2.05
            and not is_strong
        )
        # Chaos: high vig (book uncertainty) + tight three-way spread.
        spread = (max(odds_values) - min(odds_values)) if odds_values else 0.0
        is_chaos = vig >= 0.07 and spread <= 1.6 and not is_strong
        draw_gap = ev_gaps.get("had", {}).get("平", 0.0)
        is_draw_friendly = draw_gap >= 0.04 or (
            implied.get("平", 0.0) >= baseline_probs["平"] + 0.04
        )
        upset_gap = -ev_gaps.get("had", {}).get(favorite_pick or "", 0.0)
        is_upset = is_strong and upset_gap >= 0.02
        # Rule E: three-way coin flip — had pool unsuitable as leverage leg.
        implied_values = list(implied.values()) if implied else []
        implied_spread = (
            (max(implied_values) - min(implied_values)) if implied_values else 0.0
        )
        is_three_way_coinflip = (
            not is_strong
            and vig >= COINFLIP_VIG_THRESHOLD
            and implied_spread < COINFLIP_IMPLIED_SPREAD_THRESHOLD
        )
        # Rule C: high-volatility league flagged from rolling oracle ttg median.
        # Rule R2: known-hi-vol leagues fire even without samples (bootstrap).
        is_high_volatility_league = match.league in HIGH_VOL_LEAGUE_OVERRIDE
        if not is_high_volatility_league and league_volatility is not None:
            median = league_volatility.get(match.league)
            if median is not None and median >= HIGH_VOLATILITY_TTG_MEDIAN:
                is_high_volatility_league = True

        out[match.match_no] = MatchAnalytics(
            match_no=match.match_no,
            league=match.league,
            favorite_outcome=favorite_pick,
            favorite_odds=favorite_odds,
            favorite_implied=favorite_implied,
            implied_probs=implied,
            vig_pct=vig,
            dispersion=dispersion,
            popularity_score=pop_score,
            popularity_tier=pop_tier,
            baseline_probs=baseline_probs,
            ev_gaps=ev_gaps,
            is_strong_banker=is_strong,
            is_comfort_risk=is_comfort,
            is_chaos=is_chaos,
            is_draw_friendly=is_draw_friendly,
            is_upset_candidate=is_upset,
            is_three_way_coinflip=is_three_way_coinflip,
            is_high_volatility_league=is_high_volatility_league,
            is_late_kickoff=_is_late_kickoff(match.match_time),
            drift=dict(drift_entries),
        )
    return out


def _compute_ev_gaps(
    match: JczqDailyMatch,
    *,
    implied: dict[str, float],
    baseline: dict[str, float],
) -> dict[str, dict[str, float]]:
    """Per pool×pick, vig-normalized implied minus baseline reference.

    Positive gap means the market under-prices that outcome relative to the
    baseline (i.e., higher actual probability than the odds suggest).
    """

    gaps: dict[str, dict[str, float]] = {"had": {}, "hhad": {}, "ttg": {}, "hafu": {}, "crs": {}}
    if implied:
        for pick, prob in implied.items():
            gaps["had"][pick] = prob - baseline.get(pick, 0.30)

    pools: dict[str, list[JczqDailyLeg]] = {}
    for leg in match.candidates:
        pools.setdefault(leg.pool, []).append(leg)
    for pool, legs in pools.items():
        if pool == "had":
            continue
        raw = {leg.pick: 1.0 / leg.odds for leg in legs if leg.odds > 0}
        if not raw:
            continue
        total = sum(raw.values())
        if total <= 0:
            continue
        normed = {pick: prob / total for pick, prob in raw.items()}
        # For non-had pools we don't have a robust baseline; the gap field stores
        # vig-adjusted implied probability so callers can reason about leverage.
        for pick, prob in normed.items():
            gaps[pool][pick] = prob
    return gaps


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ------------------------- bucket / scoring primitives ---------------------- #


def bucket_matches(
    matches: Iterable[JczqDailyMatch],
    analytics: dict[str, MatchAnalytics],
) -> dict[str, list[JczqDailyMatch]]:
    """Categorize matches into the four cluster archetypes the generator uses.

    A match may appear in multiple buckets (it can be both upset_candidate and
    chaos). Each bucket is sorted by descending score so callers can simply pop
    from the front.
    """

    buckets: dict[str, list[tuple[float, JczqDailyMatch]]] = {
        "upset": [],
        "draw": [],
        "chaos": [],
        "strong": [],
    }
    for match in matches:
        ana = analytics.get(match.match_no)
        if ana is None:
            continue
        if ana.is_strong_banker:
            buckets["strong"].append((ana.favorite_implied, match))
            if ana.is_upset_candidate:
                gap = -ana.ev_gaps.get("had", {}).get(ana.favorite_outcome or "", 0.0)
                buckets["upset"].append((gap + 0.5, match))
        if ana.is_comfort_risk:
            draw_gap = ana.ev_gaps.get("had", {}).get("平", 0.0)
            buckets["draw"].append((draw_gap + ana.vig_pct, match))
            buckets["upset"].append((-ana.favorite_implied + 0.3, match))
        if ana.is_chaos:
            buckets["chaos"].append((ana.dispersion + ana.vig_pct, match))
            if ana.is_draw_friendly:
                draw_gap = ana.ev_gaps.get("had", {}).get("平", 0.0)
                buckets["draw"].append((draw_gap + 0.3, match))
        if ana.is_draw_friendly and not ana.is_strong_banker:
            draw_gap = ana.ev_gaps.get("had", {}).get("平", 0.0)
            buckets["draw"].append((draw_gap, match))

    sorted_out: dict[str, list[JczqDailyMatch]] = {}
    for name, items in buckets.items():
        seen: set[str] = set()
        ordered: list[JczqDailyMatch] = []
        for _, match in sorted(items, key=lambda item: item[0], reverse=True):
            if match.match_no in seen:
                continue
            ordered.append(match)
            seen.add(match.match_no)
        sorted_out[name] = ordered
    return sorted_out


@dataclass(frozen=True, slots=True)
class LegEvaluation:
    leg: JczqDailyLeg
    score: float
    ev_gap: float
    drift: float
    bucket_tags: tuple[str, ...]


def evaluate_leg(
    leg: JczqDailyLeg,
    *,
    analytics: MatchAnalytics | None,
    intent: str,
    used_pools: set[str] | None = None,
) -> LegEvaluation:
    """Score a candidate leg given an analytics snapshot and selection intent.

    Intents:
      - inspiration: prefer high-EV-gap, varied pools, mid-to-high odds
      - contrarian:  prefer +EV gap with odds in [3, 8], avoid hot favorites
      - extreme:     prefer crs/hafu with implied >= 8% but odds >= 4
      - upset:       favor hhad cover or had reversal of strong favorites
      - draw:        favor 平/平 hafu and had 平 in comfort-risk matches
      - default/main: balance odds and EV gap
    """

    used_pools = used_pools or set()
    pool_gap = 0.0
    if analytics is not None:
        gaps = analytics.ev_gaps.get(leg.pool, {})
        pool_gap = gaps.get(leg.pick, 0.0)
        # For non-had pools the gap stored is a vig-adjusted implied probability,
        # not a delta. Keep it informational by treating leverage = prob × log(odd).
    drift_value = 0.0
    if analytics is not None:
        drift_value = analytics.drift.get((leg.pool, leg.pick), 0.0)

    odds = max(1.01, leg.odds)
    log_odds = math.log(odds)
    pool_diversity = 0.4 if leg.pool not in used_pools else 0.0
    bucket_tags: list[str] = []
    score = 0.0

    if analytics is not None:
        if analytics.is_strong_banker:
            bucket_tags.append("strong")
        if analytics.is_comfort_risk:
            bucket_tags.append("comfort")
        if analytics.is_draw_friendly:
            bucket_tags.append("draw")
        if analytics.is_chaos:
            bucket_tags.append("chaos")
        if analytics.is_upset_candidate:
            bucket_tags.append("upset")

    intent = intent.lower()
    if intent == "inspiration":
        if leg.pool == "had":
            score = max(0.0, pool_gap) * 1.5 + log_odds * 0.4
        else:
            # non-had pool: leverage proportional to vig-adjusted implied prob
            score = pool_gap * log_odds * 0.8
        if 1.75 <= odds <= 8:
            score += 0.3
        score += pool_diversity
        if analytics and analytics.is_chaos:
            score += 0.4
    elif intent == "contrarian":
        score = max(0.0, pool_gap) * 1.2 + log_odds * 0.3
        if 3.0 <= odds <= 8.0:
            score += 0.25
        if leg.pool in {"ttg", "hafu", "had"}:
            score += 0.15
        if analytics and analytics.is_draw_friendly and leg.pick in {"平", "平/平"}:
            score += 0.4
        score += pool_diversity * 0.6
    elif intent == "extreme":
        if leg.pool in {"crs", "hafu"} and odds >= 4:
            score = pool_gap * log_odds + 0.6
        else:
            score = pool_gap * log_odds * 0.5
        score += min(0.5, log_odds * 0.15)
    elif intent == "upset":
        is_strong = bool(analytics and analytics.is_strong_banker)
        not_favorite = bool(
            analytics and leg.pick != analytics.favorite_outcome
        )
        if leg.pool == "hhad" and is_strong:
            score = log_odds * 0.5 + max(0.0, pool_gap)
        elif leg.pool == "had" and is_strong and not_favorite:
            score = log_odds * 0.45 + max(0.0, pool_gap) * 1.4
        else:
            score = max(0.0, pool_gap) * 0.8
    elif intent == "draw":
        if (leg.pool == "had" and leg.pick == "平") or (leg.pool == "hafu" and leg.pick == "平/平"):
            score = log_odds * 0.5 + max(0.0, pool_gap) * 1.6
        elif leg.pool == "ttg" and leg.pick in {"2球", "1球"}:
            score = max(0.0, pool_gap) * 0.6 + 0.2
    else:  # main / default
        score = max(0.0, pool_gap) + log_odds * 0.25 + pool_diversity * 0.5

    if drift_value:
        score += drift_value * 0.4

    # Rule C: in high-volatility leagues (rolling ttg median ≥ 2.7), low-side ttg
    # picks are systematically squeezed by blowouts; deprioritize them so the
    # generator picks 3+球 or non-ttg expressions instead.
    if (
        analytics is not None
        and analytics.is_high_volatility_league
        and leg.pool == "ttg"
        and leg.pick in {"0球", "1球", "2球"}
    ):
        score -= 0.5

    return LegEvaluation(
        leg=leg,
        score=score,
        ev_gap=pool_gap,
        drift=drift_value,
        bucket_tags=tuple(bucket_tags),
    )


def select_top_legs(
    matches: Iterable[JczqDailyMatch],
    analytics: dict[str, MatchAnalytics],
    *,
    intent: str,
    k: int,
    pool_filter: set[str] | None = None,
    odds_min: float = 0.0,
    odds_max: float = 999.0,
    avoid_match_nos: set[str] | None = None,
    enforce_pool_diversity: bool = True,
    bias_fn: "callable[[JczqDailyLeg, MatchAnalytics | None], float] | None" = None,
    skip_coinflip_had: bool = False,
    require_hhad_handicap: bool = False,
    poisson_edge_index: dict[tuple[str, str, str], float] | None = None,
    pool_min_edge: dict[str, float] | None = None,
    high_odds_had_min_edge: tuple[float, float] | None = None,
    reject_poisson_edge_below: float | None = None,
) -> list[LegEvaluation]:
    """Pick top-k legs across all matches by intent-specific score.

    `bias_fn` is an optional callable that returns an additive score bias for
    each candidate; the daily generator uses it to fold strategy-memory hints
    (pattern_buckets, oracle_learnings) into the ranking.

    Rule I/J Poisson gates (only applied to pools the model can price; hhad
    falls through):
      - `pool_min_edge`: per-pool floor (Rule J for crs).
      - `high_odds_had_min_edge`: `(odds_threshold, edge_min)` — had legs at
        or above the odds threshold are dropped unless their Poisson edge
        meets `edge_min` (Rule I-1).
      - `reject_poisson_edge_below`: drop any priced leg below this edge
        (Rule I-2 contrarian floor).
    """

    avoid_match_nos = set(avoid_match_nos or set())
    used_pools: set[str] = set()
    used_match_nos: set[str] = set()
    candidates: list[LegEvaluation] = []
    for match in matches:
        if match.match_no in avoid_match_nos:
            continue
        ana = analytics.get(match.match_no)
        for leg in match.candidates:
            if pool_filter and leg.pool not in pool_filter:
                continue
            if not (odds_min <= leg.odds <= odds_max):
                continue
            # Rule E: in coin-flip 3-way matches, had pool is not a valid leverage leg.
            if (
                skip_coinflip_had
                and leg.pool == "had"
                and ana is not None
                and ana.is_three_way_coinflip
            ):
                continue
            # Rule D: hhad legs without an explicit handicap line are unsafe — the
            # 让胜/让平/让负 label semantics depend on the line.
            if require_hhad_handicap and leg.pool == "hhad" and not leg.goal_line:
                continue
            # Rules I-1 / I-2 / J: Poisson-supported floors. Only apply when an
            # edge index is supplied. hhad has no Poisson coverage so it
            # bypasses these checks entirely.
            if poisson_edge_index is not None and leg.pool != "hhad":
                edge = poisson_edge_index.get((leg.match_no, leg.pool, leg.pick))
                if pool_min_edge and leg.pool in pool_min_edge:
                    threshold = pool_min_edge[leg.pool]
                    if edge is None or edge < threshold:
                        continue
                if (
                    high_odds_had_min_edge is not None
                    and leg.pool == "had"
                    and leg.odds >= high_odds_had_min_edge[0]
                ):
                    if edge is None or edge < high_odds_had_min_edge[1]:
                        continue
                if (
                    reject_poisson_edge_below is not None
                    and edge is not None
                    and edge < reject_poisson_edge_below
                ):
                    continue
            evaluation = evaluate_leg(leg, analytics=ana, intent=intent, used_pools=set())
            if bias_fn is not None:
                bias = bias_fn(leg, ana)
                if bias:
                    evaluation = LegEvaluation(
                        leg=evaluation.leg,
                        score=evaluation.score + bias,
                        ev_gap=evaluation.ev_gap,
                        drift=evaluation.drift,
                        bucket_tags=evaluation.bucket_tags,
                    )
            candidates.append(evaluation)
    candidates.sort(key=lambda item: item.score, reverse=True)

    selected: list[LegEvaluation] = []
    for ev in candidates:
        if len(selected) >= k:
            break
        if ev.leg.match_no in used_match_nos:
            continue
        if enforce_pool_diversity and ev.leg.pool in used_pools and len(used_pools) < 3:
            continue
        selected.append(ev)
        used_match_nos.add(ev.leg.match_no)
        used_pools.add(ev.leg.pool)
    if len(selected) < k:
        # Backfill ignoring pool diversity if we ran out.
        for ev in candidates:
            if len(selected) >= k:
                break
            if ev.leg.match_no in used_match_nos:
                continue
            selected.append(ev)
            used_match_nos.add(ev.leg.match_no)
    return selected[:k]


# ----------------------------- Poisson edge index --------------------------- #


@dataclass(frozen=True, slots=True)
class PoissonEdgeEntry:
    match_no: str
    home: str
    away: str
    league: str
    pool: str
    pick: str
    market_odd: float
    fair_odd: float
    edge: float


# pools the Poisson model can fairly price (hhad excluded — needs handicap-aware grid).
POISSON_PRICED_POOLS = ("had", "ttg", "hafu", "crs")


def compute_poisson_edges(
    matches: Iterable[JczqDailyMatch],
) -> list[PoissonEdgeEntry]:
    """Per-leg Poisson fair-odds vs market odds.

    Self-contained so the daily generator can call it without depending on
    the brief script. Returns a list sorted by descending edge.
    """

    from nutmeg.services.jczq_poisson import edge_vs_market, fit_lambdas_from_market

    rows: list[PoissonEdgeEntry] = []
    for match in matches:
        had = {leg.pick: leg.odds for leg in match.candidates if leg.pool == "had"}
        if not all(pick in had for pick in HAD_OUTCOMES):
            continue
        try:
            fit = fit_lambdas_from_market(
                had["胜"], had["平"], had["负"], max_lambda=3.5, step=0.1
            )
        except Exception:
            continue
        for leg in match.candidates:
            if leg.pool not in POISSON_PRICED_POOLS:
                continue
            edge = edge_vs_market(fit, pool=leg.pool, pick=leg.pick, market_odd=leg.odds)
            if edge is None:
                continue
            fair = leg.odds / (1 + edge) if edge > -1 else 0.0
            rows.append(
                PoissonEdgeEntry(
                    match_no=match.match_no,
                    home=match.home_team,
                    away=match.away_team,
                    league=match.league,
                    pool=leg.pool,
                    pick=leg.pick,
                    market_odd=leg.odds,
                    fair_odd=round(fair, 2),
                    edge=edge,
                )
            )
    rows.sort(key=lambda row: row.edge, reverse=True)
    return rows


def poisson_edge_index(
    rows: Iterable[PoissonEdgeEntry],
) -> dict[tuple[str, str, str], float]:
    """Lookup (match_no, pool, pick) -> edge for fast bias-fn use."""

    return {(row.match_no, row.pool, row.pick): row.edge for row in rows}
