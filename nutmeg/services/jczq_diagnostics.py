"""Diagnostic helpers for the JCZQ daily decision pipeline.

Functions here mechanize the kinds of checks an LLM would otherwise eyeball
(narrative classification, cross-ticket concentration, Kelly sizing, second-leg
conflict detection). They are pure — no I/O, no globals — so they can run in
unit tests, the brief script, or the debate workspace interchangeably.

Why this module exists: on 2026-05-06 Claude (the LLM) twice made arithmetic
errors that should have been caught mechanically:
  1. Mis-recommended `001 主胜` as a "partial cover" without noticing it was
     reverse to the B/D/E plans pushing `001 平` — see find_safe_second_legs.
  2. Failed to flag the over-concentration of `001 平` across three tickets
     (50% of main budget) — see compute_match_concentration.
The functions here surface those facts deterministically so future runs can't
miss them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from nutmeg.domain.jczq_daily import JczqDailyMatch, JczqDailyPlan


# ---------------------------------------------------------- narrative tagging


@dataclass(frozen=True, slots=True)
class TicketNarrative:
    plan_kind: str
    primary_narrative: str
    secondary_tags: tuple[str, ...]
    reasoning: str


_LOW_GOAL_TTG = {"0球", "1球", "2球"}
_LOW_GOAL_CRS = {"0:0", "0:1", "1:0"}
_DRAW_HAFU = {"平/平", "平/胜", "平/负"}


def classify_ticket_narrative(plan: JczqDailyPlan) -> TicketNarrative:
    """Tag a plan with one dominant narrative based on leg composition."""

    legs = list(plan.legs)
    if not legs:
        return TicketNarrative(plan.kind, "(空票)", (), "no legs")

    n = len(legs)

    # Special case: single-leg crs plan with strong narrative position.
    if n == 1 and legs[0].pool == "crs":
        is_low = legs[0].pick in _LOW_GOAL_CRS
        return TicketNarrative(
            plan_kind=plan.kind,
            primary_narrative="Poisson alpha 单核",
            secondary_tags=("低进球",) if is_low else ("精确比分",),
            reasoning=f"单腿 crs {legs[0].pick} — 模型 +EV 表达",
        )

    counts = {
        "low_goals": 0,
        "draw": 0,
        "chalk_favorite": 0,
        "cold_reverse": 0,
        "score_picks": 0,
        "high_goals": 0,
    }
    for leg in legs:
        if leg.pool == "ttg":
            if leg.pick in _LOW_GOAL_TTG:
                counts["low_goals"] += 1
            elif leg.pick in {"4球", "5球", "6球", "7+球"}:
                counts["high_goals"] += 1
        elif leg.pool == "crs":
            counts["score_picks"] += 1
            if leg.pick in _LOW_GOAL_CRS:
                counts["low_goals"] += 1
        elif leg.pool == "hafu":
            if "平" in leg.pick:
                counts["draw"] += 1
            if leg.pick in _DRAW_HAFU:
                counts["low_goals"] += 1
        elif leg.pool == "had":
            if leg.pick == "平":
                counts["draw"] += 1
            elif leg.pick in {"胜", "负"} and leg.odds < 2.0:
                counts["chalk_favorite"] += 1
            elif leg.pick == "负" and 2.5 <= leg.odds <= 5.5:
                counts["cold_reverse"] += 1
        elif leg.pool == "hhad":
            if leg.pick == "让平":
                counts["draw"] += 1
            elif leg.pick == "让负" and leg.goal_line and leg.goal_line.startswith("-"):
                # 让负 on a -1/-2 line means "home favorite doesn't dominate" — a
                # low-scoring/upset narrative.
                counts["low_goals"] += 1
                counts["cold_reverse"] += 1

    primary, tags, reason = _resolve_dominant_narrative(counts, n)
    return TicketNarrative(plan_kind=plan.kind, primary_narrative=primary,
                           secondary_tags=tags, reasoning=reason)


def _resolve_dominant_narrative(
    counts: dict[str, int], n: int
) -> tuple[str, tuple[str, ...], str]:
    if counts["score_picks"] >= 3:
        return "极限比分票", ("score",), f"≥3 腿 crs ({counts['score_picks']}/{n})"
    if counts["low_goals"] >= max(2, n - 1):
        return "低进球叙事", ("low_goals",), f"{counts['low_goals']}/{n} 腿低进球"
    if counts["cold_reverse"] >= 2:
        return "反热门客胜", ("cold_reverse",), f"{counts['cold_reverse']}/{n} 腿反热门"
    if counts["draw"] >= 2:
        return "卡盘平局", ("draw",), f"{counts['draw']}/{n} 腿平局/让平"
    if counts["chalk_favorite"] >= max(2, n - 1):
        return "主胜路线", ("chalk",), f"{counts['chalk_favorite']}/{n} 腿低赔热门"
    if counts["high_goals"] >= 2:
        return "大球叙事", ("high_goals",), f"{counts['high_goals']}/{n} 腿大球"
    nonzero = tuple(k for k, v in counts.items() if v > 0)
    return "混合叙事", nonzero, f"counts={counts}"


def compute_narrative_matrix(plans: Iterable[JczqDailyPlan]) -> dict:
    """Build per-plan narratives + diversity score across the day's tickets.

    Returns:
        {
            "narratives": list[TicketNarrative],
            "diversity_score": float,  # unique narratives / total plans
            "warning": str | None,     # set when ≥3 plans share a narrative
            "narrative_counts": dict[str, int],
        }
    """

    plan_list = [p for p in plans if p.legs]
    narratives = [classify_ticket_narrative(p) for p in plan_list]
    if not narratives:
        return {"narratives": [], "diversity_score": 1.0, "warning": None,
                "narrative_counts": {}}

    counts: dict[str, int] = {}
    for nt in narratives:
        counts[nt.primary_narrative] = counts.get(nt.primary_narrative, 0) + 1

    unique = len(counts)
    total = len(narratives)
    diversity = unique / total if total else 1.0

    warning = None
    overcrowded = [name for name, c in counts.items() if c >= 3]
    if overcrowded:
        warning = (
            f"⚠ 叙事单一性：{', '.join(overcrowded)} 同时出现在 ≥3 张票，"
            f"单一信号失败会连锁。"
        )
    elif diversity < 0.5:
        warning = f"⚠ 叙事多样性低（{diversity:.0%}），考虑重做部分票"

    return {
        "narratives": narratives,
        "diversity_score": round(diversity, 2),
        "warning": warning,
        "narrative_counts": counts,
    }


# ---------------------------------------------------------- match concentration


@dataclass(frozen=True, slots=True)
class MatchConcentration:
    match_no: str
    ticket_count: int
    plan_kinds: tuple[str, ...]
    total_stake: float
    budget_pct: float
    warning: str | None


def compute_match_concentration(
    plans: Iterable[JczqDailyPlan],
    *,
    stakes: dict[str, float],
    total_budget: float,
) -> list[MatchConcentration]:
    """Per-match exposure check.

    The metric is "if this match's outcome breaks against us, how much of the
    budget loses": we sum the FULL stake of every plan touching the match
    (not pro-rated per-leg). That's the right model because parlays go to zero
    on any single missed leg — losing a match means losing the whole stake on
    each plan it appears in.
    """

    records: dict[str, dict] = {}
    for plan in plans:
        if not plan.legs:
            continue
        stake = stakes.get(plan.kind, 0.0)
        if stake <= 0:
            continue
        for match_no in {leg.match_no for leg in plan.legs}:
            rec = records.setdefault(match_no, {"count": 0, "kinds": [], "stake": 0.0})
            rec["count"] += 1
            rec["kinds"].append(plan.kind)
            rec["stake"] += stake

    out: list[MatchConcentration] = []
    for match_no, rec in records.items():
        pct = rec["stake"] / total_budget if total_budget > 0 else 0.0
        if pct > 0.50:
            warning = f"⚠⚠ 单点风险 {pct:.0%}（{rec['count']} 张票）"
        elif pct > 0.40:
            warning = f"⚠ 集中度偏高 {pct:.0%}（{rec['count']} 张票）"
        else:
            warning = None
        out.append(MatchConcentration(
            match_no=match_no,
            ticket_count=rec["count"],
            plan_kinds=tuple(rec["kinds"]),
            total_stake=round(rec["stake"], 2),
            budget_pct=round(pct, 2),
            warning=warning,
        ))
    return sorted(out, key=lambda item: -item.budget_pct)


# ---------------------------------------------------------- Kelly advice


@dataclass(frozen=True, slots=True)
class KellyAdvice:
    plan_kind: str
    bet_odds: float
    fair_odds: float | None
    edge: float
    kelly_fraction: float
    half_kelly_yuan: float
    current_stake_yuan: float
    over_kelly_multiple: float
    warning: str | None


def compute_kelly_advice(
    plan: JczqDailyPlan,
    *,
    current_stake: float,
    bankroll: float,
    poisson_edge_index: dict[tuple[str, str, str], float] | None,
) -> KellyAdvice | None:
    """Half-Kelly stake suggestion for single-leg Poisson-priced tickets.

    Returns None for multi-leg parlays (Kelly for combos requires the joint
    distribution which we don't model rigorously here) or when the leg has no
    Poisson edge entry.
    """

    legs = list(plan.legs)
    if len(legs) != 1:
        return None
    leg = legs[0]
    edges = poisson_edge_index or {}
    edge = edges.get((leg.match_no, leg.pool, leg.pick))
    if edge is None or leg.odds <= 1.0:
        return None
    b = leg.odds - 1
    if b <= 0:
        return None
    kelly_frac = max(0.0, edge / b)  # negative-edge bets get 0 Kelly
    half_kelly = kelly_frac * bankroll * 0.5
    over_kelly = (current_stake / half_kelly) if half_kelly > 0 else float("inf")
    warning: str | None = None
    if half_kelly > 0 and over_kelly > 2.0:
        warning = f"⚠ 当前注金 {current_stake:.0f} 元 = Half-Kelly 的 {over_kelly:.1f}x"
    elif half_kelly == 0:
        warning = "⚠ Poisson edge 非正，Kelly 建议为 0（不应该下注）"
    fair = leg.odds / (1 + edge) if edge > -1 else None
    return KellyAdvice(
        plan_kind=plan.kind,
        bet_odds=leg.odds,
        fair_odds=round(fair, 2) if fair else None,
        edge=round(edge, 4),
        kelly_fraction=round(kelly_frac, 4),
        half_kelly_yuan=round(half_kelly, 2),
        current_stake_yuan=round(current_stake, 2),
        over_kelly_multiple=round(over_kelly, 2) if over_kelly != float("inf") else float("inf"),
        warning=warning,
    )


# ---------------------------------------------------------- second-leg filter


@dataclass(frozen=True, slots=True)
class SecondLegCandidate:
    leg_match_no: str
    pool: str
    pick: str
    odds: float
    edge: float | None
    fair_hit_rate: float
    combined_odds: float
    joint_hit_rate: float
    joint_ev: float
    independence: str
    conflicts: tuple[str, ...]


def find_safe_second_legs(
    *,
    solo_match_no: str,
    solo_pool: str,
    solo_pick: str,
    matches: Iterable[JczqDailyMatch],
    main_plans: Iterable[JczqDailyPlan],
    poisson_edge_index: dict[tuple[str, str, str], float] | None = None,
    rule_e_coinflip_match_nos: set[str] | None = None,
    require_hhad_handicap: bool = True,
) -> list[SecondLegCandidate]:
    """Find candidate second legs for a single-leg ticket with conflict detection.

    Resolves the class of bug Claude hit on 2026-05-06 (recommended `001 主胜`
    as a hedge while every other ticket pushed `001 平` — guaranteed reverse).

    Independence labels:
      - "完全独立": match not present in any main plan, no conflicts.
      - "已用过": exact same (match, pool, pick) used elsewhere — duplicate.
      - "反向": same match, same pool, different pick (had/hhad three-way mutex)
        OR crs 0:0 vs had not-平 (implied pic mutex).
      - "同向重复": same match, same pool, same pick — same as "已用过".
    """

    matches_list = list(matches)
    plans_list = list(main_plans)
    edges = poisson_edge_index or {}
    coinflip_set = rule_e_coinflip_match_nos or set()

    # Resolve solo leg's odds + hit rate so we can compute joint metrics.
    solo_odds = None
    for m in matches_list:
        if m.match_no != solo_match_no:
            continue
        for c in m.candidates:
            if c.pool == solo_pool and c.pick == solo_pick:
                solo_odds = c.odds
                break
        break
    solo_edge = edges.get((solo_match_no, solo_pool, solo_pick))
    if solo_odds is None or solo_odds <= 0:
        return []
    if solo_edge is not None:
        solo_hit_rate = (1 + solo_edge) / solo_odds
    else:
        solo_hit_rate = 1.0 / solo_odds

    # Index main-plan legs by match for conflict detection.
    main_by_match: dict[str, list[tuple[str, str]]] = {}
    for plan in plans_list:
        for leg in plan.legs:
            main_by_match.setdefault(leg.match_no, []).append((leg.pool, leg.pick))

    out: list[SecondLegCandidate] = []
    for match in matches_list:
        if match.match_no == solo_match_no:
            continue  # same match — nominally correlated; skip
        for cand in match.candidates:
            conflicts: list[str] = []
            independence = "完全独立"

            if cand.pool == "had" and match.match_no in coinflip_set:
                conflicts.append("Rule E coinflip had 禁")
            if require_hhad_handicap and cand.pool == "hhad" and not cand.goal_line:
                conflicts.append("Rule D hhad 无让球线")

            existing = main_by_match.get(match.match_no, [])
            for (epool, epick) in existing:
                if epool == cand.pool and epick == cand.pick:
                    conflicts.append(f"已用 (主单 {epool} {epick})")
                    independence = "已用过"
                elif epool == "had" and cand.pool == "had" and epick != cand.pick:
                    conflicts.append(f"反向 (主单押 had {epick})")
                    independence = "反向"
                elif epool == "hhad" and cand.pool == "hhad" and epick != cand.pick:
                    conflicts.append(f"反向 (主单押 hhad {epick})")
                    independence = "反向"
                elif (
                    epool == "crs" and epick == "0:0"
                    and cand.pool == "had" and cand.pick != "平"
                ):
                    conflicts.append("反向 (主单 crs 0:0 = had 平 隐含)")
                    independence = "反向"
                elif (
                    cand.pool == "crs" and cand.pick == "0:0"
                    and epool == "had" and epick != "平"
                ):
                    conflicts.append(f"反向 (crs 0:0 = had 平 vs 主单 had {epick})")
                    independence = "反向"

            edge = edges.get((match.match_no, cand.pool, cand.pick))
            if edge is not None and edge > -1:
                fair_hr = (1 + edge) / cand.odds if cand.odds > 0 else 0.0
            else:
                fair_hr = 1.0 / cand.odds if cand.odds > 0 else 0.0

            combined = round(solo_odds * cand.odds, 2)
            joint_hr = round(solo_hit_rate * fair_hr, 4)
            joint_ev = round(
                (1 + (solo_edge or 0)) * (1 + (edge if edge is not None else 0)),
                4,
            )

            out.append(SecondLegCandidate(
                leg_match_no=match.match_no,
                pool=cand.pool,
                pick=cand.pick,
                odds=cand.odds,
                edge=edge,
                fair_hit_rate=round(fair_hr, 4),
                combined_odds=combined,
                joint_hit_rate=joint_hr,
                joint_ev=joint_ev,
                independence=independence,
                conflicts=tuple(conflicts),
            ))

    # Rank: independent first (by joint hit rate desc), then everything else.
    out.sort(key=lambda c: (
        0 if c.independence == "完全独立" and not c.conflicts else 1,
        -c.joint_hit_rate,
    ))
    return out


# ----------------------------------------------- Rule O: legality validator
#
# 国家体彩规则：同一比赛场次不同玩法不可混合过关。
# 来源：国家体育总局《竞彩"自由过关"上线了！轻松投注更出彩》
# https://www.sport.gov.cn/n20001280/n20745751/n20767297/c21177108/content.html
#
# Detector returns one violation per offending plan; brief Section 7 and the
# debate compare step both call this so any structurally-illegal ticket gets
# flagged before the user can place it.


@dataclass(frozen=True, slots=True)
class SameMatchPoolViolation:
    plan_kind: str
    plan_name: str
    match_no: str
    pools: tuple[str, ...]  # e.g. ("ttg", "hhad")
    picks: tuple[str, ...]  # parallel to pools
    severity: str  # "blocking" — these tickets cannot legally be placed.


def check_same_match_pool_legality(
    plans: Iterable[JczqDailyPlan],
) -> list[SameMatchPoolViolation]:
    """Detect plans that combine same-match different-pool legs in one ticket.

    Per 国家体彩 mixed-parlay rules a single ticket may NOT multiply legs from
    the same match across different pools (had/hhad/ttg/hafu/crs). Stacking two
    same-pool legs from the same match is also illegal in 单关 mode and pointless
    in mixed mode (only one outcome can win), so we treat any same-match
    repetition inside a plan as a blocking violation.

    Returns one violation per offending (plan, match) pair. An empty list means
    every plan is structurally legal.
    """

    violations: list[SameMatchPoolViolation] = []
    for plan in plans:
        if not plan.legs:
            continue
        by_match: dict[str, list] = {}
        for leg in plan.legs:
            by_match.setdefault(leg.match_no, []).append(leg)
        for match_no, legs in by_match.items():
            if len(legs) <= 1:
                continue
            violations.append(
                SameMatchPoolViolation(
                    plan_kind=plan.kind,
                    plan_name=plan.name,
                    match_no=match_no,
                    pools=tuple(leg.pool for leg in legs),
                    picks=tuple(leg.pick for leg in legs),
                    severity="blocking",
                )
            )
    return violations
