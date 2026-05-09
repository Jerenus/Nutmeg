"""Diagnostics module tests — narrative classification, match concentration,
Kelly advice, and second-leg conflict detection.

These functions exist to mechanize what an LLM would otherwise eyeball, so
their tests are mostly about edge cases the LLM tends to miss (e.g. the
"001 主胜与 B/D/E 反向" cover bug).
"""

from __future__ import annotations

from nutmeg.domain.jczq_daily import JczqDailyLeg, JczqDailyMatch, JczqDailyPlan
from nutmeg.services.jczq_diagnostics import (
    KellyAdvice,
    MatchConcentration,
    SecondLegCandidate,
    TicketNarrative,
    apply_rule_l_concentration_cap,
    apply_rule_l_story_cap,
    apply_rule_n_late_kickoff_cap,
    classify_ticket_narrative,
    compute_kelly_advice,
    compute_match_concentration,
    compute_narrative_matrix,
    enforce_main_plan_pool_diversity,
    find_safe_second_legs,
)


def _leg(match_no, pool, pick, odds, *, goal_line="", league="日职", home="H", away="A"):
    return JczqDailyLeg(
        match_no=match_no, league=league, home_team=home, away_team=away,
        pool=pool, play=pool, pick=pick, odds=odds, logic="", goal_line=goal_line,
    )


def _plan(kind, *legs):
    legs_list = list(legs)
    total = 1.0
    for leg in legs_list:
        total *= leg.odds
    return JczqDailyPlan(
        name=kind, kind=kind, description="", legs=legs_list,
        total_odds=round(total, 2), two_yuan_return=round(total*2, 2), risk_note="",
    )


# --------------------------------------------------------- narrative classify


def test_classify_poisson_solo_single_crs_leg() -> None:
    plan = _plan("poisson_solo", _leg("周三003", "crs", "0:0", 11.0))
    out = classify_ticket_narrative(plan)
    assert isinstance(out, TicketNarrative)
    assert out.primary_narrative == "Poisson alpha 单核"


def test_classify_low_goals_when_majority_legs_are_low_scoring() -> None:
    plan = _plan(
        "main",
        _leg("周三003", "hhad", "让负", 1.71, goal_line="-1"),
        _leg("周三008", "ttg", "1球", 3.70),
        _leg("周三002", "ttg", "2球", 3.40),
        _leg("周三001", "had", "平", 3.25),
    )
    out = classify_ticket_narrative(plan)
    assert out.primary_narrative == "低进球叙事"


def test_classify_cold_reverse_when_two_or_more_had_negs_at_mid_odds() -> None:
    plan = _plan(
        "contrarian",
        _leg("周三005", "had", "负", 2.85),
        _leg("周三008", "had", "负", 3.10),
        _leg("周三009", "hhad", "让平", 4.15, goal_line="-1"),
    )
    out = classify_ticket_narrative(plan)
    assert out.primary_narrative == "反热门客胜"


def test_classify_chalk_route_when_majority_low_odds_favorites() -> None:
    plan = _plan(
        "stable_base",
        _leg("周三007", "had", "胜", 1.52),
        _leg("周三002", "had", "胜", 1.60),
    )
    out = classify_ticket_narrative(plan)
    assert out.primary_narrative == "主胜路线"


def test_classify_extreme_score_when_all_legs_are_crs() -> None:
    plan = _plan(
        "extreme",
        _leg("周三008", "crs", "0:0", 7.80),
        _leg("周三007", "crs", "0:0", 65.00),
        _leg("周三003", "crs", "0:0", 11.00),
        _leg("周三001", "crs", "0:0", 11.00),
    )
    out = classify_ticket_narrative(plan)
    assert out.primary_narrative == "极限比分票"


# --------------------------------------------------------- narrative matrix


def test_narrative_matrix_flags_low_diversity_when_three_plans_same_narrative() -> None:
    """Warn when ≥3 plans share the same primary narrative — single-signal failure
    risk. This is what we missed on 5/06 (B/main + draw_cluster + extreme all
    pushing low-scoring narratives, plus 001 平 cross-cutting them)."""
    p1 = _plan("main", _leg("a", "ttg", "1球", 4.0), _leg("b", "ttg", "1球", 3.5),
               _leg("c", "ttg", "2球", 3.4), _leg("d", "ttg", "1球", 3.7))
    p2 = _plan("contrarian", _leg("e", "ttg", "1球", 3.3), _leg("f", "ttg", "2球", 3.2),
               _leg("g", "ttg", "1球", 4.5))
    p3 = _plan("inspiration", _leg("h", "ttg", "1球", 4.5), _leg("i", "ttg", "2球", 3.5),
               _leg("j", "hafu", "平/平", 4.0))
    p4 = _plan("stable_base", _leg("x", "had", "胜", 1.55), _leg("y", "had", "胜", 1.6))
    matrix = compute_narrative_matrix([p1, p2, p3, p4])
    assert matrix["narrative_counts"].get("低进球叙事", 0) >= 3, (
        "fixture should produce 3 plans with low-goals narrative"
    )
    assert matrix["warning"] is not None
    assert "低进球叙事" in matrix["warning"]


def test_narrative_matrix_no_warning_when_diverse() -> None:
    p_chalk = _plan("stable_base", _leg("a", "had", "胜", 1.5), _leg("b", "had", "胜", 1.6))
    p_low = _plan("main", _leg("c", "ttg", "1球", 3.5), _leg("d", "ttg", "2球", 3.3),
                  _leg("e", "ttg", "1球", 4.0), _leg("f", "had", "平", 3.2))
    p_solo = _plan("poisson_solo", _leg("g", "crs", "0:0", 11.0))
    p_cold = _plan("contrarian", _leg("h", "had", "负", 2.8), _leg("i", "had", "负", 3.1),
                   _leg("j", "hhad", "让平", 4.0, goal_line="-1"))
    matrix = compute_narrative_matrix([p_chalk, p_low, p_solo, p_cold])
    assert matrix["diversity_score"] >= 0.75
    assert matrix["warning"] is None


# --------------------------------------------------------- match concentration


def test_concentration_warns_when_match_appears_in_three_or_more_tickets() -> None:
    """Mirrors today's 001 平 case: appeared in B (25), D (15), E (10) → 50/100 = 50%."""
    p_b = _plan("main", _leg("003", "hhad", "让负", 1.71, goal_line="-1"),
                _leg("008", "ttg", "1球", 3.7), _leg("002", "ttg", "2球", 3.4),
                _leg("001", "had", "平", 3.25))
    p_d = _plan("contrarian", _leg("007", "ttg", "2球", 7.3),
                _leg("004", "hhad", "让平", 3.6, goal_line="-1"),
                _leg("001", "had", "平", 3.25))
    p_e = _plan("extreme", _leg("008", "crs", "0:0", 7.8), _leg("007", "crs", "0:0", 65),
                _leg("003", "crs", "0:0", 11.0), _leg("001", "crs", "0:0", 11.0))
    stakes = {"main": 25.0, "contrarian": 15.0, "extreme": 10.0}
    out = compute_match_concentration([p_b, p_d, p_e], stakes=stakes, total_budget=100.0)
    by_match = {item.match_no: item for item in out}
    assert by_match["001"].ticket_count == 3
    assert by_match["001"].budget_pct == 0.50  # 25+15+10 = 50, 50/100 = 0.5
    assert by_match["001"].warning is not None
    assert "001" in [item.match_no for item in out if item.warning]


def test_concentration_no_warning_below_threshold() -> None:
    p_a = _plan("stable_base", _leg("007", "had", "胜", 1.52), _leg("002", "had", "胜", 1.60))
    p_c = _plan("poisson_solo", _leg("003", "crs", "0:0", 11.0))
    stakes = {"stable_base": 25.0, "poisson_solo": 25.0}
    out = compute_match_concentration([p_a, p_c], stakes=stakes, total_budget=100.0)
    assert all(item.warning is None for item in out)


# --------------------------------------------------------- Rule L hard cap (R3)


def test_rule_l_cap_drops_match_from_lowest_priority_plans_when_overexposed() -> None:
    """5/07 002 was in 5 plans (A/B/C/D/E). Rule L hard cap (R3) trims that
    down to ≤3 by dropping the leg from the lowest-priority plans first.
    Priority (most-protected → most-droppable):
      stable_base > poisson_solo > main > inspiration > contrarian
      > draw_cluster > upset_cluster > false_signal > extreme
    """
    p_a = _plan("stable_base", _leg("002", "had", "胜", 1.62), _leg("003", "had", "胜", 1.58))
    p_b = _plan("main", _leg("002", "ttg", "2球", 3.30), _leg("003", "ttg", "2球", 3.30),
                _leg("006", "ttg", "1球", 4.00), _leg("005", "had", "平", 4.00))
    p_c = _plan("poisson_solo", _leg("002", "crs", "0:0", 12.0), _leg("005", "crs", "0:0", 13.0))
    p_d = _plan("contrarian", _leg("002", "ttg", "1球", 4.50), _leg("001", "had", "平", 5.80),
                _leg("006", "hhad", "让平", 3.15, goal_line="+1"))
    p_e = _plan("extreme", _leg("002", "crs", "0:0", 12.0), _leg("003", "crs", "0:0", 12.5),
                _leg("006", "crs", "0:0", 9.25))

    capped = apply_rule_l_concentration_cap([p_a, p_b, p_c, p_d, p_e], max_per_match=3)

    plans_with_002 = [p for p in capped if any(leg.match_no == "002" for leg in p.legs)]
    assert len(plans_with_002) <= 3, (
        f"002 still in {len(plans_with_002)} plans after R3 enforcement"
    )
    by_kind = {p.kind: p for p in capped}
    assert any(leg.match_no == "002" for leg in by_kind["stable_base"].legs)
    assert any(leg.match_no == "002" for leg in by_kind["poisson_solo"].legs)
    assert any(leg.match_no == "002" for leg in by_kind["main"].legs)
    assert not any(leg.match_no == "002" for leg in by_kind["extreme"].legs)
    assert not any(leg.match_no == "002" for leg in by_kind["contrarian"].legs)


def test_rule_l_cap_recomputes_total_odds_after_dropping_leg() -> None:
    """When a leg is dropped, the parlay's total_odds and two_yuan_return
    must be recomputed to match the surviving legs.
    Fixture must satisfy R3's feasibility gate: ≥ max_per_match + 2 unique
    matches and demand < supply.
    """
    over = _plan("extreme",
                 _leg("002", "crs", "0:0", 12.0),
                 _leg("003", "crs", "0:0", 12.5),
                 _leg("006", "crs", "0:0", 9.25))
    keeper_a = _plan("stable_base",
                     _leg("002", "had", "胜", 1.62),
                     _leg("007", "had", "胜", 1.55))
    keeper_b = _plan("main",
                     _leg("002", "ttg", "2球", 3.3),
                     _leg("008", "ttg", "1球", 4.0))
    keeper_c = _plan("poisson_solo", _leg("002", "crs", "0:0", 12.0))
    keeper_d = _plan("contrarian",
                     _leg("002", "ttg", "1球", 4.5),
                     _leg("009", "had", "平", 5.0))

    capped = apply_rule_l_concentration_cap(
        [keeper_a, keeper_b, keeper_c, keeper_d, over], max_per_match=3
    )
    new_extreme = next(p for p in capped if p.kind == "extreme")
    assert all(leg.match_no != "002" for leg in new_extreme.legs)
    raw_product = 12.5 * 9.25
    assert new_extreme.total_odds == round(raw_product, 2)
    assert new_extreme.two_yuan_return == round(raw_product * 2, 2)


def test_rule_l_cap_preserves_plan_kinds_when_no_safe_trim_available() -> None:
    """When every plan touching the over-exposed match would drop below its
    minimum leg count if trimmed, R3 must not kill those plans — plan
    diversity wins over strict cap enforcement. The violation is accepted."""
    p_a = _plan("stable_base", _leg("002", "had", "胜", 1.62))
    p_b = _plan("main", _leg("002", "ttg", "2球", 3.3), _leg("005", "had", "胜", 1.4))
    p_c = _plan("poisson_solo", _leg("002", "crs", "0:0", 12.0))
    p_e = _plan("extreme", _leg("002", "crs", "0:0", 12.0))  # 1 leg < min 2

    capped = apply_rule_l_concentration_cap(
        [p_a, p_b, p_c, p_e], max_per_match=2
    )
    kinds = {p.kind for p in capped}
    assert kinds == {"stable_base", "main", "poisson_solo", "extreme"}


def test_rule_l_cap_no_op_when_already_compliant() -> None:
    p_a = _plan("stable_base", _leg("002", "had", "胜", 1.62), _leg("003", "had", "胜", 1.58))
    p_b = _plan("main", _leg("002", "ttg", "2球", 3.3), _leg("005", "had", "平", 4.0))
    capped = apply_rule_l_concentration_cap([p_a, p_b], max_per_match=3)
    assert len(capped) == 2
    assert capped[0].legs == p_a.legs
    assert capped[1].legs == p_b.legs


# --------------------------------------------------------- Rule R3.1 story cap


def test_rule_l_story_cap_drops_repeated_pick_from_lowest_priority_plan() -> None:
    """5/08 incident: 008 ttg 1球 was in B + C + E (3 plans). When 008 went
    5 goals, all three plans lost the same leg. R3.1 caps a (match, pool,
    pick) story at 2 plans by default — drops the 3rd from the lowest-
    priority plan. R3 (match-level) cap stays compatible."""
    p_b = _plan(
        "main",
        _leg("008", "ttg", "1球", 9.5),
        _leg("005", "had", "胜", 1.73),
        _leg("002", "had", "平", 3.35),
        _leg("011", "hhad", "让平", 3.5, goal_line="+1"),
    )
    p_c = _plan(
        "poisson_solo",
        _leg("009", "crs", "0:0", 11.0),
        _leg("008", "ttg", "1球", 9.5),  # same story as B
    )
    p_e = _plan(
        "extreme",
        _leg("009", "crs", "0:0", 11.0),
        _leg("008", "ttg", "1球", 9.5),  # 3rd repeat of 008 ttg 1球
        _leg("011", "hhad", "让平", 3.5, goal_line="+1"),
        _leg("006", "ttg", "1球", 5.9),
    )
    capped = apply_rule_l_story_cap([p_b, p_c, p_e], max_per_story=2)
    by_kind = {p.kind: p for p in capped}
    # The 008 ttg 1球 story should now appear in ≤2 plans (B + C kept;
    # E's 008 leg trimmed because extreme is the lowest priority).
    appearances = sum(
        1 for p in capped if any(
            leg.match_no == "008" and leg.pool == "ttg" and leg.pick == "1球"
            for leg in p.legs
        )
    )
    assert appearances <= 2
    # main and poisson_solo (most-protected) keep their 008 leg
    assert any(
        leg.match_no == "008" and leg.pool == "ttg" for leg in by_kind["main"].legs
    )
    assert any(
        leg.match_no == "008" and leg.pool == "ttg" for leg in by_kind["poisson_solo"].legs
    )
    # extreme's 008 leg dropped (still has 3 other legs, above min_legs=2)
    assert not any(
        leg.match_no == "008" and leg.pool == "ttg" for leg in by_kind["extreme"].legs
    )


def test_rule_l_story_cap_distinct_picks_in_same_match_not_collapsed() -> None:
    """A story is (match_no, pool, pick) — different picks in the same
    match are different stories. 002 had 平 vs 002 ttg 1球 are independent
    even though both are on 002."""
    p_b = _plan("main", _leg("002", "had", "平", 3.35))
    p_c = _plan("poisson_solo", _leg("002", "ttg", "1球", 5.8))
    p_d = _plan("contrarian", _leg("002", "crs", "0:0", 16.0))
    capped = apply_rule_l_story_cap([p_b, p_c, p_d], max_per_story=2)
    # 002 appears in 3 plans but as 3 distinct stories → no trim
    assert len(capped[0].legs) == 1
    assert len(capped[1].legs) == 1
    assert len(capped[2].legs) == 1


def test_rule_l_story_cap_preserves_plan_min_legs() -> None:
    """If trimming would drop a parlay below its min_legs floor, skip it."""
    p_a = _plan("main", _leg("008", "ttg", "1球", 9.5), _leg("009", "crs", "0:0", 11.0))
    p_b = _plan("inspiration", _leg("008", "ttg", "1球", 9.5), _leg("011", "hhad", "让平", 3.5))
    # Both already at min_legs=2; adding a 3rd repeater that would force a trim.
    p_c = _plan("contrarian", _leg("008", "ttg", "1球", 9.5), _leg("006", "ttg", "1球", 5.9))
    capped = apply_rule_l_story_cap([p_a, p_b, p_c], max_per_story=2)
    # Lowest-priority plan in this set is contrarian; trimming its 008 leg
    # would drop it to 1 leg (below min=2). Skip and accept violation.
    assert len(capped[2].legs) == 2


def test_rule_l_story_cap_no_op_when_already_compliant() -> None:
    p_a = _plan("main", _leg("008", "ttg", "1球", 9.5), _leg("005", "had", "胜", 1.73))
    p_b = _plan("contrarian", _leg("008", "ttg", "1球", 9.5), _leg("006", "ttg", "1球", 5.9))
    # 008 ttg 1球 in 2 plans — exactly at cap=2.
    capped = apply_rule_l_story_cap([p_a, p_b], max_per_story=2)
    assert capped[0].legs == p_a.legs
    assert capped[1].legs == p_b.legs


# --------------------------------------------------------- Rule R6 main diversity


def test_rule_r6_main_swaps_overrepresented_pool_when_above_threshold() -> None:
    """5/07 main was 3 ttg + 1 had平 (75% ttg) → all-low-goals narrative.
    R6 swaps 1 ttg leg for a different-pool candidate to break concentration."""
    p_main = _plan(
        "main",
        _leg("003", "ttg", "2球", 3.3),
        _leg("006", "ttg", "1球", 4.0),
        _leg("002", "ttg", "2球", 3.3),
        _leg("005", "had", "平", 4.0),
    )
    swap_candidates = [
        _leg("004", "hhad", "让胜", 2.5, goal_line="-1"),
        _leg("007", "had", "胜", 1.6),
    ]
    out = enforce_main_plan_pool_diversity(p_main, swap_candidates=swap_candidates)
    pool_counts = {p: sum(1 for leg in out.legs if leg.pool == p) for p in {"ttg", "had", "hhad"}}
    assert pool_counts["ttg"] <= 2, f"ttg should be ≤2/4 after R6 swap, got {pool_counts}"
    assert any(leg.match_no == "004" and leg.pool == "hhad" for leg in out.legs)
    expected_product = 1.0
    for leg in out.legs:
        expected_product *= leg.odds
    assert out.total_odds == round(expected_product, 2)


def test_rule_r6_no_op_when_pool_ratio_within_threshold() -> None:
    p_main = _plan(
        "main",
        _leg("003", "ttg", "2球", 3.3),
        _leg("006", "ttg", "1球", 4.0),
        _leg("002", "had", "胜", 1.6),
        _leg("005", "hhad", "让胜", 2.5, goal_line="-1"),
    )  # 2 ttg + 1 had + 1 hhad → 50% max
    out = enforce_main_plan_pool_diversity(
        p_main, swap_candidates=[_leg("004", "had", "胜", 1.7)]
    )
    assert out.legs == p_main.legs


def test_rule_r6_no_op_for_non_main_plan() -> None:
    p_extreme = _plan(
        "extreme",
        _leg("003", "crs", "0:0", 12.5),
        _leg("002", "crs", "0:0", 12.0),
        _leg("006", "crs", "0:0", 9.25),
    )  # 100% crs but kind != main
    out = enforce_main_plan_pool_diversity(
        p_extreme, swap_candidates=[_leg("004", "ttg", "2球", 3.3)]
    )
    assert out.legs == p_extreme.legs


# --------------------------------------------------------- Rule R4 late_kickoff


def test_rule_n_late_kickoff_cap_drops_excess_legs_from_main() -> None:
    """5/07: 周四006 (08:30 Beijing) was 'unknown' at next-day review and
    sat in main + D + E. R4 caps main/inspiration to ≤1 late-kickoff leg
    per ticket so a single delayed result doesn't pin multiple plans."""
    # main has 2 late-kickoff legs (周四005, 周四006) — must shed one.
    p_main = _plan(
        "main",
        _leg("周四005", "ttg", "1球", 4.0),
        _leg("周四006", "ttg", "1球", 4.5),
        _leg("周四002", "ttg", "2球", 3.3),
        _leg("周四003", "had", "胜", 1.65),
    )
    # inspiration with single late leg — within cap, untouched.
    p_insp = _plan(
        "inspiration",
        _leg("周四005", "crs", "1:0", 6.0),
        _leg("周四001", "had", "胜", 2.5),
    )
    capped = apply_rule_n_late_kickoff_cap(
        [p_main, p_insp], late_match_nos={"周四005", "周四006"}
    )
    new_main = next(p for p in capped if p.kind == "main")
    new_insp = next(p for p in capped if p.kind == "inspiration")
    main_late_count = sum(
        1 for leg in new_main.legs if leg.match_no in {"周四005", "周四006"}
    )
    assert main_late_count <= 1
    # inspiration keeps its single late leg
    assert new_insp.legs == p_insp.legs


def test_rule_n_late_kickoff_cap_skips_non_targeted_kinds() -> None:
    """stable_base / poisson_solo / extreme are not capped — they
    intentionally use whatever match has the highest signal."""
    p_solo = _plan(
        "poisson_solo",
        _leg("周四005", "crs", "0:0", 13.0),
        _leg("周四006", "ttg", "1球", 4.0),
    )
    p_extreme = _plan(
        "extreme",
        _leg("周四005", "crs", "0:0", 13.0),
        _leg("周四006", "crs", "0:0", 9.25),
        _leg("周四002", "crs", "0:0", 12.0),
    )
    capped = apply_rule_n_late_kickoff_cap(
        [p_solo, p_extreme], late_match_nos={"周四005", "周四006"}
    )
    # Both untouched — only main/inspiration are affected by R4.
    assert capped[0].legs == p_solo.legs
    assert capped[1].legs == p_extreme.legs


def test_rule_n_late_kickoff_cap_preserves_plan_min_legs() -> None:
    """If trimming would drop the plan below min_legs (main floor = 2),
    skip the trim and accept the violation rather than break the plan."""
    p_main = _plan(
        "main",
        _leg("周四005", "ttg", "1球", 4.0),
        _leg("周四006", "ttg", "1球", 4.5),
    )  # only 2 legs, both late — trim would leave 1, below main's min=2
    capped = apply_rule_n_late_kickoff_cap([p_main], late_match_nos={"周四005", "周四006"})
    assert capped[0].legs == p_main.legs


def test_rule_r6_no_op_when_swap_candidates_all_share_same_match_no() -> None:
    """If candidate's match is already in the plan, skipping it preserves
    Rule O (no same-match different-pool inside one ticket)."""
    p_main = _plan(
        "main",
        _leg("003", "ttg", "2球", 3.3),
        _leg("006", "ttg", "1球", 4.0),
        _leg("002", "ttg", "2球", 3.3),
        _leg("005", "had", "平", 4.0),
    )
    swap_candidates = [
        _leg("003", "hhad", "让胜", 2.5, goal_line="-1"),
        _leg("002", "had", "胜", 1.6),
    ]
    out = enforce_main_plan_pool_diversity(p_main, swap_candidates=swap_candidates)
    assert out.legs == p_main.legs


# --------------------------------------------------------- kelly advice


def test_kelly_advice_for_single_leg_with_strong_edge() -> None:
    """003 比分 0:0 @ 11.0, edge +21.9% → Half-Kelly ~1% bankroll."""
    plan = _plan("poisson_solo", _leg("003", "crs", "0:0", 11.0))
    edges = {("003", "crs", "0:0"): 0.219}
    advice = compute_kelly_advice(plan, current_stake=25.0, bankroll=100.0,
                                  poisson_edge_index=edges)
    assert isinstance(advice, KellyAdvice)
    assert 0 < advice.kelly_fraction < 0.05
    assert 0 < advice.half_kelly_yuan < 5.0  # Half-Kelly should be ~1.1 元
    assert advice.over_kelly_multiple > 5  # 25 元 vs ~1 元 = >20x over Half-Kelly
    assert advice.warning is not None


def test_kelly_advice_returns_none_for_multi_leg_plan() -> None:
    plan = _plan("main", _leg("003", "ttg", "1球", 4.45), _leg("008", "ttg", "1球", 3.7),
                 _leg("002", "ttg", "2球", 3.4), _leg("001", "had", "平", 3.25))
    edges = {("003", "ttg", "1球"): 0.085}
    out = compute_kelly_advice(plan, current_stake=25.0, bankroll=100.0,
                               poisson_edge_index=edges)
    assert out is None  # Kelly for parlays is out of scope


def test_kelly_advice_returns_none_when_edge_missing() -> None:
    plan = _plan("poisson_solo", _leg("003", "crs", "0:0", 11.0))
    out = compute_kelly_advice(plan, current_stake=25.0, bankroll=100.0,
                               poisson_edge_index={})
    assert out is None


# --------------------------------------------------------- safe second legs


def _match_with_legs(num: str, *leg_specs):
    legs = [_leg(num, p, pk, o, goal_line=gl) for (p, pk, o, gl) in leg_specs]
    return JczqDailyMatch(
        match_no=num, match_date="2026-05-06", match_time="20:00", league="日职",
        home_team=f"H{num}", away_team=f"A{num}", status="Selling",
        hot_direction="主胜低赔", role="均衡分歧场", confidence_note="", candidates=legs,
    )


def test_second_leg_filter_rejects_reverse_had_when_main_pushes_draw() -> None:
    """Today's 001 主胜 reverse-cover bug: B/D/E push 001 平; suggesting 001 主胜
    must be marked '反向' (or excluded from independent ranking)."""
    matches = [
        _match_with_legs("周三001", ("had", "胜", 2.05, ""), ("had", "平", 3.25, ""),
                          ("had", "负", 3.0, "")),
        _match_with_legs("周三009", ("ttg", "1球", 3.30, ""), ("crs", "0:0", 6.20, "")),
    ]
    p_b = _plan("main", _leg("周三001", "had", "平", 3.25))
    p_d = _plan("contrarian", _leg("周三001", "had", "平", 3.25))
    edges = {
        ("周三003", "crs", "0:0"): 0.219,
        ("周三001", "had", "胜"): -0.10,
        ("周三001", "had", "负"): -0.12,
        ("周三009", "ttg", "1球"): -0.018,
        ("周三009", "crs", "0:0"): 0.025,
    }
    # Need a synthetic 003 match for the solo leg
    matches_with_solo = matches + [
        _match_with_legs("周三003", ("crs", "0:0", 11.0, "")),
    ]
    out = find_safe_second_legs(
        solo_match_no="周三003", solo_pool="crs", solo_pick="0:0",
        matches=matches_with_solo, main_plans=[p_b, p_d],
        poisson_edge_index=edges,
    )
    by_key = {(c.leg_match_no, c.pool, c.pick): c for c in out}
    cand_001_win = by_key.get(("周三001", "had", "胜"))
    assert cand_001_win is not None
    assert cand_001_win.independence == "反向", (
        f"001 主胜 must be flagged '反向' since main 001 平 is pushed; "
        f"got independence='{cand_001_win.independence}', conflicts={cand_001_win.conflicts}"
    )


def test_second_leg_filter_rejects_already_used_legs() -> None:
    matches = [
        _match_with_legs("周三007", ("had", "胜", 1.52, "")),
        _match_with_legs("周三003", ("crs", "0:0", 11.0, "")),
    ]
    p_a = _plan("stable_base", _leg("周三007", "had", "胜", 1.52))
    out = find_safe_second_legs(
        solo_match_no="周三003", solo_pool="crs", solo_pick="0:0",
        matches=matches, main_plans=[p_a],
        poisson_edge_index={("周三003", "crs", "0:0"): 0.219,
                             ("周三007", "had", "胜"): -0.126},
    )
    cand_007_win = next((c for c in out if c.leg_match_no == "周三007" and c.pool == "had"), None)
    assert cand_007_win is not None
    assert cand_007_win.independence == "已用过"


def test_second_leg_filter_ranks_independent_first() -> None:
    matches = [
        _match_with_legs("周三007", ("had", "胜", 1.52, "")),
        _match_with_legs("周三009", ("ttg", "1球", 3.30, "")),
        _match_with_legs("周三003", ("crs", "0:0", 11.0, "")),
    ]
    p_a = _plan("stable_base", _leg("周三007", "had", "胜", 1.52))
    out = find_safe_second_legs(
        solo_match_no="周三003", solo_pool="crs", solo_pick="0:0",
        matches=matches, main_plans=[p_a],
        poisson_edge_index={("周三003", "crs", "0:0"): 0.219,
                             ("周三007", "had", "胜"): -0.126,
                             ("周三009", "ttg", "1球"): -0.018},
    )
    # The 009 candidate (independent) should rank above the 007 candidate (already used)
    independent_idx = next(i for i, c in enumerate(out)
                           if c.leg_match_no == "周三009" and c.pool == "ttg")
    used_idx = next(i for i, c in enumerate(out)
                    if c.leg_match_no == "周三007" and c.pool == "had")
    assert independent_idx < used_idx
