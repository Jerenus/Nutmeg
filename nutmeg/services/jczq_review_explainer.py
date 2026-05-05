"""Structured "why we missed" generator for the daily review.

Per missed plan, builds a deterministic, machine-extractable narrative that
identifies (a) which leg killed the ticket, (b) which oracle alternative would
have hit, and (c) which decision rules to soften / harden.

An optional `Completer` Protocol lets callers swap in an LLM when they want
prose, but the default path is purely rule-based so the whole pipeline stays
deterministic and offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class Completer(Protocol):
    """Optional LLM completion seam (kept Portkey/OpenAI-shape for now)."""

    def complete(self, prompt: str) -> str: ...


@dataclass(frozen=True, slots=True)
class MissedPlanExplanation:
    plan_kind: str
    plan_name: str
    miss_reason: str
    killer_legs: tuple[dict[str, Any], ...]
    oracle_pick_diffs: tuple[dict[str, Any], ...]
    extracted_rules: tuple[str, ...]
    narrative: str


def explain_missed_plans(
    *,
    plan_reviews: list[dict[str, Any]],
    results: dict[str, dict[str, str]],
    completer: Completer | None = None,
) -> list[MissedPlanExplanation]:
    """Inspect plan_reviews and emit structured explanations for non-hits."""

    explanations: list[MissedPlanExplanation] = []
    for plan in plan_reviews:
        if plan.get("all_hit"):
            continue
        legs = plan.get("legs") or []
        killer_legs: list[dict[str, Any]] = []
        diffs: list[dict[str, Any]] = []
        for leg in legs:
            if leg.get("hit"):
                continue
            killer_legs.append(_killer_summary(leg))
            diff = _oracle_diff(leg, results.get(str(leg.get("match_no") or "")) or {})
            if diff:
                diffs.append(diff)
        rules = _extracted_rules(plan, killer_legs, diffs)
        narrative = _render_narrative(plan, killer_legs, diffs, rules, completer=completer)
        explanations.append(
            MissedPlanExplanation(
                plan_kind=str(plan.get("plan_id") or plan.get("plan_kind") or "unknown"),
                plan_name=str(plan.get("plan_name") or ""),
                miss_reason=str(
                    plan.get("miss_reason")
                    or "; ".join(_short(leg) for leg in killer_legs)
                ),
                killer_legs=tuple(killer_legs),
                oracle_pick_diffs=tuple(diffs),
                extracted_rules=tuple(rules),
                narrative=narrative,
            )
        )
    return explanations


def _killer_summary(leg: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_no": leg.get("match_no"),
        "pool": leg.get("pool"),
        "pick": leg.get("pick"),
        "actual_pick": leg.get("actual_pick") or leg.get("actual"),
        "original_odds": leg.get("original_odds") or leg.get("odds"),
        "actual_odds": leg.get("actual_odds"),
        "score": leg.get("score"),
    }


def _oracle_diff(leg: dict[str, Any], actual_row: dict[str, Any]) -> dict[str, Any] | None:
    pool = str(leg.get("pool") or "")
    actual_pick = leg.get("actual_pick") or actual_row.get(pool)
    actual_odds = leg.get("actual_odds") or actual_row.get(f"{pool}_odds")
    if not actual_pick or not actual_odds:
        return None
    return {
        "match_no": leg.get("match_no"),
        "pool": pool,
        "missed_pick": leg.get("pick"),
        "winning_pick": actual_pick,
        "winning_odds": actual_odds,
        "score": leg.get("score") or actual_row.get("score"),
    }


def _extracted_rules(
    plan: dict[str, Any],
    killer_legs: list[dict[str, Any]],
    diffs: list[dict[str, Any]],
) -> list[str]:
    rules: list[str] = []
    plan_kind = str(plan.get("plan_id") or plan.get("plan_kind") or "")
    if "stable_base" in plan_kind:
        if any(_implied_odds(leg.get("original_odds")) <= 1.45 for leg in killer_legs):
            rules.append("strong_banker_low_price_drift")
    if "main" in plan_kind:
        for leg in killer_legs:
            if str(leg.get("pool")) == "had" and str(leg.get("pick")) == "平":
                rules.append("comfort_draw_protection_overused")
                break
    if "inspiration" in plan_kind or "contrarian" in plan_kind:
        if all(str(leg.get("pool")) in {"had", "hhad"} for leg in killer_legs):
            rules.append("widen_pool_diversity")
    if any(diff for diff in diffs if str(diff.get("pool")) == "ttg"):
        rules.append("recheck_total_goals_distribution")
    if any(diff for diff in diffs if str(diff.get("pool")) == "hafu"):
        rules.append("hafu_pick_off_target")
    if not rules:
        rules.append("retain_plan_review_for_pattern_history")
    return list(dict.fromkeys(rules))  # de-dupe preserve order


def _render_narrative(
    plan: dict[str, Any],
    killer_legs: list[dict[str, Any]],
    diffs: list[dict[str, Any]],
    rules: list[str],
    *,
    completer: Completer | None,
) -> str:
    summary_pieces = [
        f"{plan.get('plan_name')}（{plan.get('plan_id')}）整票未中。",
        "塌房腿：" + "; ".join(_short(leg) for leg in killer_legs[:3]) + "。",
    ]
    if diffs:
        summary_pieces.append(
            "Oracle 同玩法本可命中：" + "; ".join(
                f"{d['match_no']} {d['pool']} {d['winning_pick']}@{d['winning_odds']}"
                for d in diffs[:3]
            ) + "。"
        )
    if rules:
        summary_pieces.append("规则建议：" + "/".join(rules) + "。")
    text = "".join(summary_pieces)
    if completer is None:
        return text
    try:
        return completer.complete(text)
    except Exception:  # pragma: no cover - LLM seam, deterministic fallback
        return text


def _short(leg: dict[str, Any]) -> str:
    return (
        f"{leg.get('match_no')}{leg.get('pool')} {leg.get('pick')}->"
        f"{leg.get('actual_pick') or leg.get('actual')}"
    )


def _implied_odds(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 9.99


@dataclass(frozen=True, slots=True)
class OracleLearning:
    league: str
    pool: str
    successful_pick: str
    sample_size: int = 1
    cumulative_odds: float = 0.0


def aggregate_oracle_learnings(
    plan_reviews: list[dict[str, Any]],
    *,
    context_matches: list[dict[str, Any]],
) -> dict[tuple[str, str, str], OracleLearning]:
    """Collapse plan-review oracle data into (league, pool, pick) buckets."""

    league_by_match = {
        str(item.get("match_no")): str(item.get("league") or "")
        for item in context_matches
    }
    learnings: dict[tuple[str, str, str], OracleLearning] = field(default_factory=dict)  # type: ignore[arg-type]
    learnings = {}
    for plan in plan_reviews:
        for leg in plan.get("legs") or []:
            if leg.get("hit"):
                continue
            actual_pick = leg.get("actual_pick") or leg.get("actual")
            actual_odds = leg.get("actual_odds")
            if not actual_pick:
                continue
            try:
                price = float(actual_odds) if actual_odds else 0.0
            except (TypeError, ValueError):
                price = 0.0
            key = (
                league_by_match.get(str(leg.get("match_no")), ""),
                str(leg.get("pool") or ""),
                str(actual_pick),
            )
            current = learnings.get(key)
            if current is None:
                learnings[key] = OracleLearning(
                    league=key[0],
                    pool=key[1],
                    successful_pick=key[2],
                    sample_size=1,
                    cumulative_odds=price,
                )
            else:
                learnings[key] = OracleLearning(
                    league=current.league,
                    pool=current.pool,
                    successful_pick=current.successful_pick,
                    sample_size=current.sample_size + 1,
                    cumulative_odds=current.cumulative_odds + price,
                )
    return learnings
