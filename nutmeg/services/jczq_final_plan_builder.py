"""Build the PDF-ready structured ``final-plan.json`` from a thin skeleton.

The daily debate's human adjudication produces a *ticket skeleton* — which
legs go on which ticket and at what stake — but the full schema consumed by
``jczq_final_plan_pdf`` also needs per-leg detail (league/home/away/odds/
goal_line/logic), ticket odds math, and a concentration audit. Hand-authoring
that whole JSON every day is the known workflow gap.

This module closes it: given a hand-authored ``final-plan-input.json`` skeleton
plus the day's ``context.json`` (written by ``build_brief``), it joins each leg
against the brief's candidates, computes ``total_odds`` / ``theoretical_payout``
/ portfolio ``total_stake``, and runs the shared-match + Rule O audit.

What stays the human's job (judgment, no machine source): which legs, stakes,
``hit_probability`` / ``expected_value`` (optional skeleton fields), narrative
text. What this removes from the daily hand-write: all leg detail, all odds
math, the concentration audit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["FinalPlanBuilderError", "build_structured_final_plan"]


class FinalPlanBuilderError(ValueError):
    """A leg references a (match_no, pool, pick) absent from the brief context."""


def build_structured_final_plan(
    *,
    run_date: str,
    context_path: Path,
    skeleton_path: Path,
) -> dict[str, Any]:
    """Enrich a ticket skeleton into the full PDF-ready final-plan dict.

    Args:
        run_date: the plan's run date (``YYYY-MM-DD``).
        context_path: the day's ``context.json`` (brief candidates source).
        skeleton_path: the hand-authored ``final-plan-input.json``.

    Raises:
        FinalPlanBuilderError: a skeleton leg has no matching brief candidate.
    """

    skeleton = json.loads(Path(skeleton_path).read_text(encoding="utf-8"))
    candidate_index = _candidate_index(Path(context_path))

    favorite_id = skeleton.get("favorite_ticket_id")
    tickets: list[dict[str, Any]] = []
    for raw_ticket in skeleton.get("tickets", []):
        tickets.append(
            _build_ticket(raw_ticket, candidate_index, favorite_id=favorite_id)
        )

    total_stake = sum(int(t["stake"]) for t in tickets)
    portfolio_metrics: dict[str, Any] = {
        "total_stake": total_stake,
        "comparison": {},
    }
    # EV is the human's call — only surface it if the skeleton supplied per-ticket
    # numbers (a conflict-engine plan often omits unverified EV entirely).
    known_evs = [t["expected_value"] for t in tickets if t.get("expected_value") is not None]
    if known_evs:
        portfolio_metrics["total_expected_value_known"] = round(sum(known_evs), 2)

    plan: dict[str, Any] = {
        "run_date": run_date,
        "budget_total": skeleton.get("budget_total", total_stake),
        "rule_environment": skeleton.get("rule_environment", []),
        "config_variant": skeleton.get("config_variant", ""),
        "config_variant_note": skeleton.get("config_variant_note", ""),
        "portfolio_metrics": portfolio_metrics,
        "tickets": tickets,
        "excluded_matches": skeleton.get("excluded_matches", []),
        "concentration_audit": _concentration_audit(tickets),
        "favorite_ticket_id": favorite_id,
        "human_decision_summary": skeleton.get("human_decision_summary", ""),
    }
    return plan


def _candidate_index(
    context_path: Path,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Index brief candidates by ``(match_no, pool, pick)`` with match detail."""

    ctx = json.loads(context_path.read_text(encoding="utf-8"))
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for match in ctx.get("matches", []):
        for cand in match.get("candidates", []):
            key = (cand["match_no"], cand["pool"], cand["pick"])
            index[key] = {
                "league": cand.get("league") or match.get("league", ""),
                "home": cand.get("home_team") or match.get("home_team", ""),
                "away": cand.get("away_team") or match.get("away_team", ""),
                "odds": float(cand["odds"]),
                "goal_line": cand.get("goal_line", "") or "",
                "logic": cand.get("logic", "") or "",
            }
    return index


def _build_ticket(
    raw_ticket: dict[str, Any],
    candidate_index: dict[tuple[str, str, str], dict[str, Any]],
    *,
    favorite_id: str | None,
) -> dict[str, Any]:
    legs: list[dict[str, Any]] = []
    total_odds = 1.0
    for raw_leg in raw_ticket.get("legs", []):
        leg = _build_leg(raw_leg, candidate_index)
        legs.append(leg)
        total_odds *= leg["odds"]

    total_odds = round(total_odds, 2)
    stake = int(raw_ticket["stake"])
    ticket: dict[str, Any] = {
        "id": raw_ticket["id"],
        "name": raw_ticket.get("name", ""),
        "kind": raw_ticket.get("kind", ""),
        "stake": stake,
        "total_odds": total_odds,
        "theoretical_payout": round(stake * total_odds, 2),
        "favorite": raw_ticket["id"] == favorite_id,
        "favorite_reason": raw_ticket.get("favorite_reason", ""),
        "legs": legs,
    }
    # Optional human-supplied numbers / notes pass through unchanged.
    for optional in ("hit_probability", "expected_value", "variant_note"):
        if optional in raw_ticket:
            ticket[optional] = raw_ticket[optional]
    return ticket


def _build_leg(
    raw_leg: dict[str, Any],
    candidate_index: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    match_no = raw_leg["match_no"]
    pool = raw_leg["pool"]
    pick = raw_leg["pick"]
    detail = candidate_index.get((match_no, pool, pick))
    if detail is None:
        raise FinalPlanBuilderError(
            f"leg {match_no} {pool} {pick} not found in brief context — "
            "check match_no/pool/pick spelling against context.json candidates"
        )
    leg: dict[str, Any] = {
        "match_no": match_no,
        "league": raw_leg.get("league") or detail["league"],
        "home": raw_leg.get("home") or detail["home"],
        "away": raw_leg.get("away") or detail["away"],
        "pool": pool,
        "pick": pick,
        # A pinned skeleton odds (brief-confirmed, may differ from stale
        # context) wins over the context candidate.
        "odds": float(raw_leg["odds"]) if "odds" in raw_leg else detail["odds"],
        "logic": raw_leg.get("logic") or detail["logic"],
    }
    goal_line = raw_leg.get("goal_line") or detail["goal_line"]
    if goal_line:
        leg["goal_line"] = goal_line
    if "poisson_edge" in raw_leg:
        leg["poisson_edge"] = raw_leg["poisson_edge"]
    return leg


def _concentration_audit(tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect cross-ticket shared matches and intra-ticket Rule O violations.

    Rule O: a single ticket must not bet the same match on two different
    pools (e.g. had 胜 + hhad 让胜 on the same match) — that is a hidden
    correlated double-down, not diversification.
    """

    # Shared matches across tickets.
    match_to_tickets: dict[str, list[str]] = {}
    match_to_stake: dict[str, int] = {}
    for ticket in tickets:
        seen_here: set[str] = set()
        for leg in ticket["legs"]:
            mn = leg["match_no"]
            if mn in seen_here:
                continue
            seen_here.add(mn)
            match_to_tickets.setdefault(mn, []).append(ticket["id"])
            match_to_stake[mn] = match_to_stake.get(mn, 0) + ticket["stake"]

    shared_matches = [
        {
            "match_no": mn,
            "tickets": ids,
            "stake_at_risk": match_to_stake[mn],
            "narrative_diversification": "",
        }
        for mn, ids in sorted(match_to_tickets.items())
        if len(ids) > 1
    ]

    # Rule O: same match, two different pools, within one ticket.
    rule_o_violations = 0
    for ticket in tickets:
        pools_by_match: dict[str, set[str]] = {}
        for leg in ticket["legs"]:
            pools_by_match.setdefault(leg["match_no"], set()).add(leg["pool"])
        rule_o_violations += sum(
            1 for pools in pools_by_match.values() if len(pools) > 1
        )

    return {
        "shared_matches": shared_matches,
        "rule_o_violations": rule_o_violations,
    }
