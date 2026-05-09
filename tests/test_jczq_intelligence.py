"""Unit tests for the JCZQ analytics core."""

from __future__ import annotations

from nutmeg.domain.jczq_daily import JczqDailyLeg, JczqDailyMatch
from nutmeg.services.jczq_intelligence import (
    HIGH_VOL_LEAGUE_OVERRIDE,
    LeaguePriorBaseline,
    bucket_matches,
    compute_analytics,
    evaluate_leg,
    select_top_legs,
)


def _leg(match_no: str, league: str, pool: str, pick: str, odds: float) -> JczqDailyLeg:
    return JczqDailyLeg(
        match_no=match_no,
        league=league,
        home_team="H",
        away_team="A",
        pool=pool,
        play="play",
        pick=pick,
        odds=odds,
        logic="",
        goal_line="",
        odds_update="",
    )


def _match(match_no: str, league: str, candidates: list[JczqDailyLeg]) -> JczqDailyMatch:
    return JczqDailyMatch(
        match_no=match_no,
        match_date="2026-05-03",
        match_time="22:00:00",
        league=league,
        home_team="H",
        away_team="A",
        status="Selling",
        hot_direction="主胜低赔(1.10)",
        role="强胆场",
        confidence_note="胜平负方向可做胆，但让胜不能自动视为稳胆。",
        candidates=candidates,
    )


def _strong_match() -> JczqDailyMatch:
    return _match(
        "周日020",
        "意甲",
        [
            _leg("周日020", "意甲", "had", "胜", 1.12),
            _leg("周日020", "意甲", "had", "平", 6.70),
            _leg("周日020", "意甲", "had", "负", 18.00),
            _leg("周日020", "意甲", "hhad", "让胜", 2.30),
            _leg("周日020", "意甲", "hhad", "让平", 3.55),
            _leg("周日020", "意甲", "hhad", "让负", 2.50),
            _leg("周日020", "意甲", "hafu", "负/平", 28.00),
        ],
    )


def _comfort_match() -> JczqDailyMatch:
    return _match(
        "周日005",
        "德乙",
        [
            _leg("周日005", "德乙", "had", "胜", 1.92),
            _leg("周日005", "德乙", "had", "平", 3.75),
            _leg("周日005", "德乙", "had", "负", 4.10),
            _leg("周日005", "德乙", "hafu", "平/平", 5.30),
        ],
    )


def _chaos_match() -> JczqDailyMatch:
    return _match(
        "周日015",
        "英超",
        [
            _leg("周日015", "英超", "had", "胜", 2.09),
            _leg("周日015", "英超", "had", "平", 3.35),
            _leg("周日015", "英超", "had", "负", 3.50),
        ],
    )


def test_compute_analytics_classifies_strong_comfort_chaos_buckets() -> None:
    matches = [_strong_match(), _comfort_match(), _chaos_match()]
    analytics = compute_analytics(matches, baseline=LeaguePriorBaseline())

    assert set(analytics.keys()) == {"周日020", "周日005", "周日015"}
    assert analytics["周日020"].is_strong_banker is True
    assert analytics["周日020"].is_comfort_risk is False
    assert analytics["周日005"].is_comfort_risk is True
    assert analytics["周日005"].is_strong_banker is False
    assert analytics["周日015"].is_strong_banker is False
    assert 0.97 <= sum(analytics["周日020"].implied_probs.values()) <= 1.03
    assert analytics["周日020"].vig_pct > 0.0


def test_bucket_matches_routes_each_archetype_to_relevant_buckets() -> None:
    matches = [_strong_match(), _comfort_match(), _chaos_match()]
    analytics = compute_analytics(matches)
    buckets = bucket_matches(matches, analytics)

    assert any(m.match_no == "周日020" for m in buckets["strong"])
    assert any(m.match_no == "周日005" for m in buckets["draw"])
    # Strong + upset_candidate or comfort match could also seed upset bucket;
    # the key invariant is that we don't return an empty cluster set.
    assert sum(len(v) for v in buckets.values()) >= 3


def test_evaluate_leg_weights_inspiration_intent_toward_high_ev_pool_diversity() -> None:
    matches = [_strong_match()]
    analytics = compute_analytics(matches)
    ana = analytics["周日020"]

    leg_had_平 = next(
        leg for leg in matches[0].candidates if leg.pool == "had" and leg.pick == "平"
    )
    leg_hhad_让负 = next(
        leg for leg in matches[0].candidates if leg.pool == "hhad" and leg.pick == "让负"
    )

    score_inspiration = evaluate_leg(leg_had_平, analytics=ana, intent="inspiration").score
    score_main = evaluate_leg(leg_had_平, analytics=ana, intent="main").score
    upset_score = evaluate_leg(leg_hhad_让负, analytics=ana, intent="upset").score

    # 平 in a strong-banker upset has positive EV gap → both intents should score it
    assert score_inspiration > 0
    assert score_main > 0
    assert upset_score > 0


def test_select_top_legs_respects_pool_filter_and_avoid_set() -> None:
    matches = [_strong_match(), _comfort_match(), _chaos_match()]
    analytics = compute_analytics(matches)

    picks = select_top_legs(
        matches,
        analytics,
        intent="inspiration",
        k=2,
        pool_filter={"had"},
        avoid_match_nos={"周日020"},
        enforce_pool_diversity=False,
    )

    assert len(picks) == 2
    assert all(ev.leg.pool == "had" for ev in picks)
    assert all(ev.leg.match_no != "周日020" for ev in picks)


def test_select_top_legs_blends_optional_bias_function() -> None:
    matches = [_strong_match(), _comfort_match()]
    analytics = compute_analytics(matches)

    def bias(leg: JczqDailyLeg, _ana) -> float:
        # Force comfort-match draws above everything else
        return 5.0 if leg.match_no == "周日005" and leg.pick == "平" else 0.0

    picks = select_top_legs(
        matches,
        analytics,
        intent="contrarian",
        k=1,
        pool_filter={"had"},
        bias_fn=bias,
        enforce_pool_diversity=False,
    )

    assert picks
    assert picks[0].leg.match_no == "周日005"
    assert picks[0].leg.pick == "平"


# ---------------------------------------------------- Rule R2 (5/08) ---


def test_rule_r2_known_high_volatility_leagues_flagged_without_samples() -> None:
    """Bootstrap leagues hardcoded as hi-vol fire the flag even when the
    rolling oracle volatility map is empty (or omits that league).

    Evidence: 5/07 had 4 of 5 matches in 欧罗巴 / 解放者杯 / 沙职 with avg
    goals ≥ 3; Rule C failed because oracle samples were too sparse to
    compute a stable per-league median. R2 adds the known-hi-vol override.
    """

    europa = _match("周四002", "欧罗巴", [
        _leg("周四002", "欧罗巴", "had", "胜", 1.62),
        _leg("周四002", "欧罗巴", "had", "平", 4.00),
        _leg("周四002", "欧罗巴", "had", "负", 5.30),
    ])
    libertadores = _match("周四005", "解放者杯", [
        _leg("周四005", "解放者杯", "had", "胜", 1.37),
        _leg("周四005", "解放者杯", "had", "平", 4.50),
        _leg("周四005", "解放者杯", "had", "负", 7.00),
    ])
    sa_pro = _match("周四001", "沙职", [
        _leg("周四001", "沙职", "had", "胜", 8.00),
        _leg("周四001", "沙职", "had", "平", 5.50),
        _leg("周四001", "沙职", "had", "负", 1.20),
    ])
    eredivisie = _match("周四010", "荷甲", [
        _leg("周四010", "荷甲", "had", "胜", 1.80),
        _leg("周四010", "荷甲", "had", "平", 3.60),
        _leg("周四010", "荷甲", "had", "负", 4.20),
    ])
    matches = [europa, libertadores, sa_pro, eredivisie]
    analytics = compute_analytics(matches)

    assert analytics["周四002"].is_high_volatility_league is True
    assert analytics["周四005"].is_high_volatility_league is True
    assert analytics["周四001"].is_high_volatility_league is True
    assert analytics["周四010"].is_high_volatility_league is False
    # The constant itself should be a non-empty frozenset for callers to inspect.
    assert "欧罗巴" in HIGH_VOL_LEAGUE_OVERRIDE
    assert "解放者杯" in HIGH_VOL_LEAGUE_OVERRIDE
    assert "沙职" in HIGH_VOL_LEAGUE_OVERRIDE


def test_rule_r2_override_does_not_clobber_oracle_signal_for_other_leagues() -> None:
    """When a non-override league has a high-vol oracle median, the existing
    Rule C path still fires."""

    j1 = _match("周日010", "日职", [
        _leg("周日010", "日职", "had", "胜", 1.92),
        _leg("周日010", "日职", "had", "平", 3.30),
        _leg("周日010", "日职", "had", "负", 4.50),
    ])
    analytics = compute_analytics([j1], league_volatility={"日职": 3.0})
    assert analytics["周日010"].is_high_volatility_league is True


# ---------------------------------------------------- Rule R4 (5/08) late_kickoff


def _late_match(match_no: str, hhmmss: str) -> JczqDailyMatch:
    """Build a match whose start time is `hhmmss` (Beijing). Used to
    exercise the late-kickoff flag."""
    return JczqDailyMatch(
        match_no=match_no,
        match_date="2026-05-08",
        match_time=hhmmss,
        league="解放者杯",
        home_team="H",
        away_team="A",
        status="Selling",
        hot_direction="主胜低赔(1.50)",
        role="均衡分歧场",
        confidence_note="",
        candidates=[
            _leg(match_no, "解放者杯", "had", "胜", 1.50),
            _leg(match_no, "解放者杯", "had", "平", 3.80),
            _leg(match_no, "解放者杯", "had", "负", 6.50),
        ],
    )


# ---------------------------------------------------- Rule R7.1 (5/09) hhad filter


def test_rule_r71_select_top_legs_filters_hhad_with_strongly_negative_poisson_edge() -> None:
    """5/08 incident: 011 hhad 让平 (+1) had Poisson edge ~-16% — model
    strongly opposed — yet appeared in B/D/E because select_top_legs
    bypassed all Poisson gates for hhad. R7.1 adds an explicit
    hhad_min_edge parameter; setting it to -0.10 drops hhad legs below
    that threshold."""

    from nutmeg.services.jczq_intelligence import select_top_legs

    # Synthetic: two matches with hhad legs, one strongly model-opposed.
    bad_hhad_match = JczqDailyMatch(
        match_no="周五011",
        match_date="2026-05-08",
        match_time="22:00:00",
        league="英冠",
        home_team="赫尔城",
        away_team="米尔沃尔",
        status="Selling",
        hot_direction="客胜低赔(2.30)",
        role="均衡分歧场",
        confidence_note="",
        candidates=[
            _leg("周五011", "英冠", "had", "胜", 3.20),
            _leg("周五011", "英冠", "had", "平", 3.05),
            _leg("周五011", "英冠", "had", "负", 2.30),
            JczqDailyLeg(
                match_no="周五011", league="英冠", home_team="赫尔城", away_team="米尔沃尔",
                pool="hhad", play="让球胜平负", pick="让平", odds=3.50,
                logic="", goal_line="+1", odds_update="",
            ),
        ],
    )
    ok_hhad_match = JczqDailyMatch(
        match_no="周五012",
        match_date="2026-05-08",
        match_time="23:00:00",
        league="西甲",
        home_team="莱万特",
        away_team="奥萨苏纳",
        status="Selling",
        hot_direction="主胜低赔(2.27)",
        role="均衡分歧场",
        confidence_note="",
        candidates=[
            _leg("周五012", "西甲", "had", "胜", 2.27),
            _leg("周五012", "西甲", "had", "平", 3.20),
            _leg("周五012", "西甲", "had", "负", 3.30),
            JczqDailyLeg(
                match_no="周五012", league="西甲", home_team="莱万特", away_team="奥萨苏纳",
                pool="hhad", play="让球胜平负", pick="让平", odds=3.45,
                logic="", goal_line="-1", odds_update="",
            ),
        ],
    )
    matches = [bad_hhad_match, ok_hhad_match]
    analytics = compute_analytics(matches)
    # Manually craft the Poisson edge index: 011 让平 strongly opposed,
    # 012 让平 mildly negative (within tolerance).
    edge_index = {
        ("周五011", "hhad", "让平"): -0.16,  # below -0.10 threshold → drop
        ("周五012", "hhad", "让平"): -0.05,  # within tolerance → keep
    }
    picks = select_top_legs(
        matches,
        analytics,
        intent="contrarian",
        k=4,
        pool_filter={"hhad"},
        enforce_pool_diversity=False,
        poisson_edge_index=edge_index,
        hhad_min_edge=-0.10,
    )
    pick_match_nos = {ev.leg.match_no for ev in picks}
    assert "周五012" in pick_match_nos
    assert "周五011" not in pick_match_nos, (
        "R7.1 should filter 011 让平 (edge -16% < -10% threshold)"
    )


def test_rule_r71_select_top_legs_default_keeps_hhad_unfiltered_when_min_edge_unset() -> None:
    """Backward compatibility: callers that don't pass hhad_min_edge
    preserve the pre-R7.1 behavior (hhad bypasses Poisson gates)."""

    from nutmeg.services.jczq_intelligence import select_top_legs

    bad_hhad_match = JczqDailyMatch(
        match_no="周五011",
        match_date="2026-05-08",
        match_time="22:00:00",
        league="英冠",
        home_team="赫尔城",
        away_team="米尔沃尔",
        status="Selling",
        hot_direction="客胜低赔(2.30)",
        role="均衡分歧场",
        confidence_note="",
        candidates=[
            _leg("周五011", "英冠", "had", "胜", 3.20),
            _leg("周五011", "英冠", "had", "平", 3.05),
            _leg("周五011", "英冠", "had", "负", 2.30),
            JczqDailyLeg(
                match_no="周五011", league="英冠", home_team="赫尔城", away_team="米尔沃尔",
                pool="hhad", play="让球胜平负", pick="让平", odds=3.50,
                logic="", goal_line="+1", odds_update="",
            ),
        ],
    )
    matches = [bad_hhad_match]
    analytics = compute_analytics(matches)
    edge_index = {("周五011", "hhad", "让平"): -0.16}
    picks = select_top_legs(
        matches,
        analytics,
        intent="contrarian",
        k=2,
        pool_filter={"hhad"},
        enforce_pool_diversity=False,
        poisson_edge_index=edge_index,
        # hhad_min_edge intentionally omitted
    )
    assert any(ev.leg.match_no == "周五011" for ev in picks), (
        "Without hhad_min_edge, 011 should still appear (backward compat)"
    )


def test_rule_r4_late_kickoff_flag_set_for_morning_beijing_kickoffs() -> None:
    """5/07 周四006 麦独立 vs 弗拉门戈 kicked off 08:30 Beijing — its result
    was still 'unknown' when the next-day review ran 10:00 Beijing. R4
    flags such matches so generator can cap exposure to one leg per
    main/inspiration ticket."""

    early_dawn = _late_match("周一001", "06:00:00")  # late
    morning = _late_match("周一002", "08:30:00")  # late
    afternoon = _late_match("周一003", "15:00:00")  # not late
    evening = _late_match("周一004", "21:00:00")  # not late
    midnight = _late_match("周一005", "02:00:00")  # not late (settles ~04:00)

    analytics = compute_analytics([early_dawn, morning, afternoon, evening, midnight])
    assert analytics["周一001"].is_late_kickoff is True
    assert analytics["周一002"].is_late_kickoff is True
    assert analytics["周一003"].is_late_kickoff is False
    assert analytics["周一004"].is_late_kickoff is False
    assert analytics["周一005"].is_late_kickoff is False
