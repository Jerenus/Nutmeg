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
    classify_ticket_narrative,
    compute_kelly_advice,
    compute_match_concentration,
    compute_narrative_matrix,
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
