"""Tests for jczq_tiered — spec 2026-05-25 v2 A/B/D/E plan."""
from __future__ import annotations

from nutmeg.services.jczq_bold_combos import (
    HARD_LABEL,
    BoldMatch,
    PoolSignals,
    compute_pool_signals,
    ticket_theme,
)
from nutmeg.services.jczq_tiered import (
    DEFAULT_TIER_A,
    DEFAULT_TIER_B,
    DEFAULT_TIER_D,
    DEFAULT_TIER_E,
    LegReason,
    PlanContext,
    TieredPlan,
    confidence_tag_for_code,
    pick_anchor_tier,
    pick_contra_tier,
    pick_lottery_tier,
    pick_main_tier,
    render_tiered_plan,
    select_tiered_plan,
    v2_candidate_pool,
)


_BANNED = ("胜率", "edge", "+EV", "正期望", "推荐下注", "重仓")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _match(no: str, **overrides) -> BoldMatch:
    """Synthetic BoldMatch with all 4 markets populated by default."""
    return BoldMatch(
        match_no=no,
        league=overrides.get("league", "L"),
        home=overrides.get("home", "H"),
        away=overrides.get("away", "A"),
        tc_odds=overrides.get(
            "tc_odds", {"home": 2.0, "draw": 3.3, "away": 3.5}
        ),
        euro_odds=overrides.get("euro_odds", {}),
        euro_opening=overrides.get("euro_opening", {}),
        per_book_odds=overrides.get("per_book_odds", {}),
        euro_fair_prob=overrides.get("euro_fair_prob", {}),
        tags=overrides.get("tags", set()),
        vig=overrides.get("vig", 0.13),
        hhad_odds=overrides.get(
            "hhad_odds",
            {"home": 3.0, "draw": 3.3, "away": 2.1},
        ),
        hhad_line=overrides.get("hhad_line", -1.0),
        ttg_odds=overrides.get(
            "ttg_odds",
            {f"total_{k}": 4.0 + k for k in range(8)},
        ),
        crs_odds=overrides.get(
            "crs_odds",
            {"s01s00": 6.5, "s00s00": 9.0, "s02s01": 7.5},
        ),
    )


def _anchor_match(no: str, home_odds: float, hhad_home_odds: float = 2.0) -> BoldMatch:
    """A match with a low-odds favourite and an hhad cover option."""
    return _match(
        no,
        tc_odds={"home": home_odds, "draw": 3.5, "away": 5.0},
        hhad_odds={"home": hhad_home_odds, "draw": 3.5, "away": 2.0},
        hhad_line=-1.0,
    )


# ---------------------------------------------------------------------------
# T1 — LegReason
# ---------------------------------------------------------------------------


def test_leg_reason_holds_four_segments() -> None:
    r = LegReason(
        why_match="m", why_market="k", why_pick="p", why_not_alt="n"
    )
    assert r.why_match == "m"
    assert r.why_market == "k"
    assert r.why_pick == "p"
    assert r.why_not_alt == "n"


def test_leg_reason_why_not_alt_optional() -> None:
    r = LegReason(why_match="m", why_market="k", why_pick="p")
    assert r.why_not_alt == ""


# ---------------------------------------------------------------------------
# T2 — v2_candidate_pool
# ---------------------------------------------------------------------------


def test_v2_candidate_pool_up_to_2_legs_per_match() -> None:
    matches = [_match(f"M{i}") for i in range(1, 5)]
    pool = v2_candidate_pool(matches)
    by_match: dict[str, list] = {}
    for lg in pool:
        by_match.setdefault(lg.match_no, []).append(lg)
    assert all(1 <= len(legs) <= 2 for legs in by_match.values()), (
        f"each match contributes 1-2 legs, got {by_match}"
    )
    assert len(pool) >= 6, (
        f"4 matches × ~2 legs → ≥6 pool, got {len(pool)}"
    )


def test_v2_candidate_pool_distinct_markets_per_match() -> None:
    matches = [_match(f"M{i}") for i in range(1, 5)]
    pool = v2_candidate_pool(matches)
    for mn in {lg.match_no for lg in pool}:
        markets = [lg.market for lg in pool if lg.match_no == mn]
        assert len(markets) == len(set(markets)), (
            f"per-match legs must come from distinct markets, got {markets}"
        )


def test_v2_candidate_pool_empty_matches() -> None:
    assert v2_candidate_pool([]) == []


def test_v2_candidate_pool_single_market_no_trim() -> None:
    matches = [
        BoldMatch(match_no=f"M{i}", league="L", home="H", away="A",
                  tc_odds={"home": 2.0, "draw": 3.3, "away": 3.5})
        for i in range(1, 7)
    ]
    pool = v2_candidate_pool(matches)
    assert all(lg.market == "had" for lg in pool)
    assert len(pool) == 6


# ---------------------------------------------------------------------------
# T3 — DEFAULT_TIER constants
# ---------------------------------------------------------------------------


def test_default_tier_a_matches_spec() -> None:
    assert DEFAULT_TIER_A.code == "A"
    assert DEFAULT_TIER_A.name == "稳健底仓"
    assert DEFAULT_TIER_A.fold_range == (2, 3)
    assert DEFAULT_TIER_A.total_odds_band == (2.5, 8.0)
    assert DEFAULT_TIER_A.base_stake_yuan == 35
    assert DEFAULT_TIER_A.max_crs_legs == 0


def test_default_tier_b_matches_spec() -> None:
    assert DEFAULT_TIER_B.fold_range == (3, 5)
    assert DEFAULT_TIER_B.total_odds_band == (30.0, 150.0)
    assert DEFAULT_TIER_B.base_stake_yuan == 35


def test_default_tier_d_matches_spec() -> None:
    assert DEFAULT_TIER_D.fold_range == (3, 4)
    assert DEFAULT_TIER_D.total_odds_band == (80.0, 300.0)
    assert DEFAULT_TIER_D.base_stake_yuan == 20
    assert DEFAULT_TIER_D.max_crs_legs == 1


def test_default_tier_e_matches_spec() -> None:
    assert DEFAULT_TIER_E.fold_range == (4, 5)
    assert DEFAULT_TIER_E.total_odds_band == (800.0, 5000.0)
    assert DEFAULT_TIER_E.base_stake_yuan == 10
    assert DEFAULT_TIER_E.max_crs_legs == 1


def test_confidence_tag_for_code() -> None:
    assert confidence_tag_for_code("A") == "⭐⭐⭐⭐"
    assert confidence_tag_for_code("B") == "⭐⭐⭐"
    assert confidence_tag_for_code("D") == "⭐⭐"
    assert confidence_tag_for_code("E") == "⭐"
    assert confidence_tag_for_code("X") == ""


# ---------------------------------------------------------------------------
# T4 — pick_anchor_tier
# ---------------------------------------------------------------------------


def test_pick_anchor_tier_picks_lowest_odds_favourites() -> None:
    # v2.1 §25.1 — at least one ≤1.65 favourite must exist in pool
    matches = [
        _anchor_match("M1", 1.60),
        _anchor_match("M2", 1.65),
        _anchor_match("M3", 1.70),
    ]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is not None
    assert 2 <= len(tier.legs) <= 3
    assert 2.5 <= tier.total_odds <= 8.0
    # v2.1 §25.1 — per-fold cap: 3-fold ≤ 5.5, 2-fold ≤ 4.0
    if len(tier.legs) == 3:
        assert tier.total_odds <= 5.5
    elif len(tier.legs) == 2:
        assert tier.total_odds <= 4.0
    assert tier.confidence_tag == "⭐⭐⭐⭐"


def test_pick_anchor_tier_hhad_cover_for_super_favourite() -> None:
    # v2.1 §25.1 — 3-fold cap 5.5: 1.90 * 1.65 * 1.70 = 5.33 ≤ 5.5
    matches = [
        _anchor_match("M1", 1.40, hhad_home_odds=1.90),
        _anchor_match("M2", 1.65),
        _anchor_match("M3", 1.70),
    ]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is not None
    m1_legs = [tl for tl in tier.legs if tl.leg.match_no == "M1"]
    assert m1_legs, "M1 (super favourite) should appear in anchor"
    assert m1_legs[0].leg.market == "hhad", (
        f"had ≤1.50 → hhad cover preferred, got {m1_legs[0].leg.market}"
    )


def test_pick_anchor_tier_empty_returns_none() -> None:
    ctx = PlanContext(pool_signals=PoolSignals())
    assert pick_anchor_tier(DEFAULT_TIER_A, [], frozenset(), ctx, []) is None


def test_pick_anchor_tier_leg_reason_filled() -> None:
    matches = [_anchor_match(f"M{i}", 1.55 + 0.05 * i) for i in range(1, 4)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is not None
    for tl in tier.legs:
        assert tl.reason.why_match
        assert tl.reason.why_market
        assert tl.reason.why_pick


# ---------------------------------------------------------------------------
# T5 — pick_main_tier + cross-tier exclusion
# ---------------------------------------------------------------------------


def test_pick_main_tier_excludes_anchor_matches() -> None:
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 9)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    excluded = frozenset({"M1", "M2"})
    tier = pick_main_tier(DEFAULT_TIER_B, pool, excluded, ctx, matches)
    if tier is not None:
        for tl in tier.legs:
            assert tl.leg.match_no not in excluded


def test_pick_main_tier_returns_none_when_no_candidates() -> None:
    ctx = PlanContext(pool_signals=PoolSignals())
    assert pick_main_tier(DEFAULT_TIER_B, [], frozenset(), ctx, []) is None


# ---------------------------------------------------------------------------
# T6 — pick_contra_tier + retired-theme skip
# ---------------------------------------------------------------------------


def test_pick_contra_tier_excludes_a_and_b_matches() -> None:
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 10)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    excluded = frozenset({"M1", "M2", "M3", "M4"})
    tier = pick_contra_tier(DEFAULT_TIER_D, pool, excluded, ctx, matches)
    if tier is not None:
        for tl in tier.legs:
            assert tl.leg.match_no not in excluded


def test_pick_contra_tier_skips_retired_themes() -> None:
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 10)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(
        pool_signals=compute_pool_signals(matches),
        retired_themes=frozenset({"平局收割"}),
    )
    tier = pick_contra_tier(DEFAULT_TIER_D, pool, frozenset(), ctx, matches)
    if tier is not None:
        legs_only = [tl.leg for tl in tier.legs]
        assert ticket_theme(legs_only)[0] != "平局收割"


# ---------------------------------------------------------------------------
# T7 — pick_lottery_tier
# ---------------------------------------------------------------------------


def test_pick_lottery_tier_honours_excluded() -> None:
    """spec §25.2.a — E now excludes A∪B∪D matches."""
    matches = [_anchor_match(f"M{i}", 2.5 + 0.4 * i) for i in range(1, 9)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    excluded = frozenset({"M1", "M2"})
    tier = pick_lottery_tier(DEFAULT_TIER_E, pool, excluded, ctx, matches)
    if tier is not None:
        assert tier.confidence_tag == "⭐"
        for tl in tier.legs:
            assert tl.leg.match_no not in excluded


def test_pick_lottery_tier_crs_cap() -> None:
    matches = [_anchor_match(f"M{i}", 5.0 + i) for i in range(1, 8)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_lottery_tier(DEFAULT_TIER_E, pool, frozenset(), ctx, matches)
    if tier is not None:
        crs_legs = sum(1 for tl in tier.legs if tl.leg.market == "crs")
        assert crs_legs <= 1


# ---------------------------------------------------------------------------
# T8 — select_tiered_plan + recommended_single
# ---------------------------------------------------------------------------


def test_select_tiered_plan_recommends_a_when_present() -> None:
    matches = [_anchor_match(f"M{i}", 1.50 + 0.05 * i) for i in range(1, 10)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0)
    if plan.tiers[0] is not None:
        assert plan.recommended_single == "A"
    else:
        # v2.1 §25.1 — A→D→B→None fallback chain
        assert plan.recommended_single in (None, "D", "B")


def test_select_tiered_plan_4_tier_slots() -> None:
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 8)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0)
    assert len(plan.tiers) == 4


def test_select_tiered_plan_propagates_retired_themes() -> None:
    history = {
        "by_theme": {
            "平局收割": {"tickets": 23, "ticket_hits": 0,
                          "legs": 63, "leg_hits": 11},
        }
    }
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 8)]
    plan = select_tiered_plan(matches, history=history, multiplier=1.0)
    assert any(rt.theme == "平局收割" for rt in plan.retired_themes)


def test_select_tiered_plan_cross_tier_exclusion() -> None:
    matches = [_anchor_match(f"M{i}", 1.85 + 0.05 * i) for i in range(1, 10)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0)
    a = plan.tiers[0]
    b = plan.tiers[1]
    d = plan.tiers[2]
    if a is not None and b is not None:
        assert a.match_nos.isdisjoint(b.match_nos), (
            "A and B must not share matches"
        )
    if a is not None and d is not None:
        assert a.match_nos.isdisjoint(d.match_nos), (
            "A and D must not share matches"
        )
    if b is not None and d is not None:
        assert b.match_nos.isdisjoint(d.match_nos), (
            "B and D must not share matches"
        )


# ---------------------------------------------------------------------------
# T9 — render_tiered_plan
# ---------------------------------------------------------------------------


def test_render_includes_hard_label_and_stake_summary() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 6)]
    plan = select_tiered_plan(
        matches, history={}, multiplier=1.0, run_date="2026-05-25"
    )
    out = render_tiered_plan(plan)
    assert out.startswith(HARD_LABEL)
    assert "💰 今日方案" in out
    assert "总建议金额" in out


def test_render_marks_recommended_single() -> None:
    matches = [_anchor_match(f"M{i}", 1.50 + 0.05 * i) for i in range(1, 6)]
    plan = select_tiered_plan(
        matches, history={}, multiplier=1.0, run_date="2026-05-25"
    )
    out = render_tiered_plan(plan)
    if plan.recommended_single is not None:
        assert f"首推一张 = {plan.recommended_single}" in out
        # v2.1 §25.1 — render differs for A vs D-fallback
        if plan.recommended_single == "A":
            assert "若只玩一张选这张" in out
        else:
            assert "A 档不出" in out


def test_render_has_no_banned_words() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 8)]
    plan = select_tiered_plan(
        matches, history={}, multiplier=1.0, run_date="2026-05-25"
    )
    out = render_tiered_plan(plan)
    body = out[len(HARD_LABEL):]
    for word in _BANNED:
        assert word not in body, f"banned word leaked: {word}"


def test_render_stake_multiplier_scales_amounts() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 6)]
    plan = select_tiered_plan(
        matches, history={}, multiplier=0.25, run_date="2026-05-25"
    )
    if plan.tiers[0] is not None:
        # 35 * 0.25 = 8.75 → 9 (banker's rounding 9 either way)
        assert plan.tiers[0].stake_yuan in (8, 9)


def test_render_shows_per_leg_three_line_reason() -> None:
    matches = [_anchor_match(f"M{i}", 1.70 + 0.05 * i) for i in range(1, 6)]
    plan = select_tiered_plan(
        matches, history={}, multiplier=1.0, run_date="2026-05-25"
    )
    out = render_tiered_plan(plan)
    if plan.tiers[0] is not None:
        assert "> 场理由：" in out
        assert "> 选法：" in out
        assert "> pick：" in out


def test_render_missing_tier_shows_honest_message() -> None:
    plan = TieredPlan(
        run_date="2026-05-25", day_chaos=8, chaos_band="平静",
        tiers=[None, None, None, None],
        recommended_single=None,
    )
    out = render_tiered_plan(plan)
    assert "稳健底仓" in out
    assert "候选不足" in out or "今日无可用方案" in out


# ---------------------------------------------------------------------------
# T10 — spec §25.1 · A 真稳健化
# ---------------------------------------------------------------------------


def test_anchor_requires_real_favourite_under_1_65() -> None:
    """spec §25.1 — pool with no had ≤ 1.65 should yield A=None."""
    matches = [
        _anchor_match("M1", 1.70),
        _anchor_match("M2", 1.85),
        _anchor_match("M3", 1.95),
    ]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is None


def test_anchor_real_favourite_at_threshold_passes() -> None:
    """spec §25.1 — exactly 1.65 satisfies the pre-check."""
    matches = [
        _anchor_match("M1", 1.65),
        _anchor_match("M2", 1.85),
        _anchor_match("M3", 1.95),
    ]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is not None


def test_anchor_3fold_total_odds_above_5_5_drops_to_2fold() -> None:
    """spec §25.1 — 3-fold > 5.5 → engine returns 2-fold under 4.0."""
    # Lowest favourite 1.55 satisfies real-fav check. 3-fold 1.55*1.85*1.95 = 5.59 > 5.5
    # → A reduces to 2-fold (1.55 * 1.85 = 2.87 ≤ 4.0).
    matches = [
        _anchor_match("M1", 1.55),
        _anchor_match("M2", 1.85),
        _anchor_match("M3", 1.95),
    ]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is not None
    assert len(tier.legs) == 2
    assert tier.total_odds <= 4.0


def test_anchor_2fold_total_odds_above_4_0_returns_none() -> None:
    """spec §25.1 — even 2-fold > 4.0 → A=None."""
    # 1.55 + 2.80 favourite → 2-fold 1.55 * 2.80 = 4.34 > 4.0
    # But _favourite_had_leg picks min odds per match — so M2's favourite is
    # whichever outcome has min odds. Use only one real-fav so 2-fold forced.
    matches = [
        _anchor_match("M1", 1.55),
        _anchor_match("M2", 2.80),
    ]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    tier = pick_anchor_tier(DEFAULT_TIER_A, pool, frozenset(), ctx, matches)
    assert tier is None


def test_recommend_single_falls_back_to_d_when_a_missing() -> None:
    """spec §25.1 — A→D→B→None: D should be recommended when A is None."""
    # No favourite ≤ 1.65 → A=None. Mix of mid-range odds gives D a chance.
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 10)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0)
    assert plan.tiers[0] is None
    if plan.tiers[2] is not None:
        assert plan.recommended_single == "D"


# ---------------------------------------------------------------------------
# T11 — spec §25.2 · BDE 跨档去重
# ---------------------------------------------------------------------------


def test_pick_lottery_tier_filters_excluded_matches() -> None:
    """spec §25.2.a — E excludes A∪B∪D match_nos."""
    matches = [_anchor_match(f"M{i}", 2.5 + 0.4 * i) for i in range(1, 10)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    excluded = frozenset({"M1", "M2", "M3"})
    tier = pick_lottery_tier(DEFAULT_TIER_E, pool, excluded, ctx, matches)
    if tier is not None:
        for tl in tier.legs:
            assert tl.leg.match_no not in excluded


def test_pick_lottery_tier_returns_none_when_pool_insufficient() -> None:
    """spec §25.2.a + Q2a — E returns None when fewer than 4 legs left."""
    matches = [_anchor_match(f"M{i}", 2.5 + 0.4 * i) for i in range(1, 5)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    # Exclude 3 of 4 matches → only 1 left, can't make a 4-fold E ticket.
    excluded = frozenset({"M1", "M2", "M3"})
    tier = pick_lottery_tier(DEFAULT_TIER_E, pool, excluded, ctx, matches)
    assert tier is None


def test_pick_contra_tier_filters_b_same_match_reverse_hhad() -> None:
    """spec §25.2.b — D rejects hhad legs that reverse B's same-match pick."""
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 10)]
    pool = v2_candidate_pool(matches)
    ctx = PlanContext(pool_signals=compute_pool_signals(matches))
    # Pretend B chose hhad['home'] on M1; D must not pick hhad['draw' / 'away']
    # on M1.
    b_hhad = {"M1": "home"}
    tier = pick_contra_tier(
        DEFAULT_TIER_D, pool, frozenset(), ctx, matches,
        b_hhad_picks=b_hhad,
    )
    if tier is not None:
        for tl in tier.legs:
            if tl.leg.match_no == "M1" and tl.leg.market == "hhad":
                assert tl.leg.pick == "home", (
                    "D must not reverse B's hhad pick on the same match"
                )


def test_select_tiered_plan_bde_disjoint_match_nos() -> None:
    """spec §25.2.a — full plan: B/D/E must not share match_nos."""
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 12)]
    plan = select_tiered_plan(matches, history={}, multiplier=1.0)
    b, d, e = plan.tiers[1], plan.tiers[2], plan.tiers[3]
    if b is not None and d is not None:
        assert b.match_nos.isdisjoint(d.match_nos)
    if b is not None and e is not None:
        assert b.match_nos.isdisjoint(e.match_nos)
    if d is not None and e is not None:
        assert d.match_nos.isdisjoint(e.match_nos)


# ---------------------------------------------------------------------------
# T12 — spec §25.3 · hhad 健康度门控
# ---------------------------------------------------------------------------


def test_hhad_health_insufficient_sample_disabled() -> None:
    """spec §25.3 — total < 30 hhad legs → disabled, no blocked picks."""
    from nutmeg.services.jczq_tiered import recent_hhad_market_health
    records = [
        {"date": "2026-05-25", "by_hhad_actual": {"让胜": 5, "让平": 2}},
        {"date": "2026-05-24", "by_hhad_actual": {"让负": 3}},
    ]
    health = recent_hhad_market_health(records)
    assert health["enabled"] is False
    assert health["blocked_picks"] == frozenset()


def test_hhad_health_let_win_dominance_blocks_other_picks() -> None:
    """spec §25.3 — 让胜 ≥ 55% → block {让平, 让负}."""
    from nutmeg.services.jczq_tiered import recent_hhad_market_health
    records = [
        {"date": f"2026-05-{d:02d}", "by_hhad_actual": {"让胜": 6, "让平": 2, "让负": 2}}
        for d in range(11, 15)
    ]
    # 40 legs total, 让胜 60%
    health = recent_hhad_market_health(records)
    assert health["enabled"] is True
    assert health["dominant"] == "让胜"
    assert health["blocked_picks"] == frozenset({"让平", "让负"})


def test_hhad_health_balanced_no_blocking() -> None:
    """spec §25.3 — no direction crosses 55% → no blocking."""
    from nutmeg.services.jczq_tiered import recent_hhad_market_health
    records = [
        {"date": f"2026-05-{d:02d}", "by_hhad_actual": {"让胜": 4, "让平": 3, "让负": 3}}
        for d in range(11, 15)
    ]
    # 40 legs, 让胜 40%, 让平 30%, 让负 30% → no dominance
    health = recent_hhad_market_health(records)
    assert health["enabled"] is True
    assert health["dominant"] == ""
    assert health["blocked_picks"] == frozenset()


def test_hhad_health_window_caps_at_14_days() -> None:
    """spec §25.3 — only the most recent 14 review records contribute."""
    from nutmeg.services.jczq_tiered import recent_hhad_market_health
    # 30 days of records — the oldest 16 should be ignored.
    records = [
        {"date": f"2026-04-{d:02d}", "by_hhad_actual": {"让平": 100}}
        for d in range(1, 17)  # 16 old days, 让平-heavy (should be ignored)
    ] + [
        {"date": f"2026-05-{d:02d}", "by_hhad_actual": {"让胜": 6, "让平": 2, "让负": 2}}
        for d in range(11, 25)  # 14 recent days, 让胜 60% dominant
    ]
    health = recent_hhad_market_health(records)
    # 14 days * 10 legs = 140 total; 让胜 = 6*14 = 84 → 60% > 55%
    assert health["total_legs"] == 14 * 10
    assert health["dominant"] == "让胜"


def test_pick_contra_tier_health_filters_hhad_picks() -> None:
    """spec §25.3 — D drops hhad legs whose pick_label is in blocked_picks."""
    from nutmeg.services.jczq_tiered import _HHAD_PICK_LABEL
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 10)]
    pool = v2_candidate_pool(matches)
    blocked = frozenset({"让平", "让负"})
    ctx = PlanContext(
        pool_signals=compute_pool_signals(matches),
        hhad_health={"blocked_picks": blocked, "enabled": True},
    )
    tier = pick_contra_tier(DEFAULT_TIER_D, pool, frozenset(), ctx, matches)
    if tier is not None:
        for tl in tier.legs:
            if tl.leg.market == "hhad":
                assert tl.leg.pick_label not in blocked


def test_pick_lottery_tier_health_filters_hhad_picks() -> None:
    """spec §25.3 — E also drops hhad legs in blocked_picks."""
    matches = [_anchor_match(f"M{i}", 2.0 + 0.4 * i) for i in range(1, 10)]
    pool = v2_candidate_pool(matches)
    blocked = frozenset({"让胜", "让平"})
    ctx = PlanContext(
        pool_signals=compute_pool_signals(matches),
        hhad_health={"blocked_picks": blocked, "enabled": True},
    )
    tier = pick_lottery_tier(DEFAULT_TIER_E, pool, frozenset(), ctx, matches)
    if tier is not None:
        for tl in tier.legs:
            if tl.leg.market == "hhad":
                assert tl.leg.pick_label not in blocked


def test_pick_main_tier_not_affected_by_hhad_health() -> None:
    """spec §25.3 — B (主方案) is NOT gated by hhad health."""
    matches = [_anchor_match(f"M{i}", 2.0 + 0.3 * i) for i in range(1, 12)]
    pool = v2_candidate_pool(matches)
    blocked = frozenset({"让平", "让负"})
    # Run B both with and without blocked picks — same outcome.
    ctx_no_block = PlanContext(pool_signals=compute_pool_signals(matches))
    ctx_block = PlanContext(
        pool_signals=compute_pool_signals(matches),
        hhad_health={"blocked_picks": blocked, "enabled": True},
    )
    b_no = pick_main_tier(DEFAULT_TIER_B, pool, frozenset(), ctx_no_block, matches)
    b_yes = pick_main_tier(DEFAULT_TIER_B, pool, frozenset(), ctx_block, matches)
    if b_no is not None and b_yes is not None:
        assert b_no.match_nos == b_yes.match_nos


# ---------------------------------------------------------------------------
# T13 — spec §25 · render integration
# ---------------------------------------------------------------------------


def test_render_shows_hhad_health_top_line_enabled() -> None:
    """spec §25.3 — when enabled, render emits the health top-line."""
    plan = TieredPlan(
        run_date="2026-05-25", day_chaos=8, chaos_band="平静",
        tiers=[None, None, None, None],
        recommended_single=None,
        hhad_health={
            "enabled": True, "total_legs": 40,
            "rates": {"让胜": 0.6, "让平": 0.2, "让负": 0.2},
            "blocked_picks": frozenset({"让平", "让负"}),
            "dominant": "让胜",
        },
    )
    out = render_tiered_plan(plan)
    assert "hhad 健康度 14d" in out
    assert "让胜 60.0%" in out


def test_render_shows_hhad_health_disabled_line() -> None:
    """spec §25.3 — insufficient sample emits the "正常开" notice."""
    plan = TieredPlan(
        run_date="2026-05-25", day_chaos=8, chaos_band="平静",
        tiers=[None, None, None, None],
        recommended_single=None,
        hhad_health={
            "enabled": False, "total_legs": 12,
            "rates": {}, "blocked_picks": frozenset(), "dominant": "",
        },
    )
    out = render_tiered_plan(plan)
    assert "样本不足" in out
    assert "contrarian 正常开" in out


def test_render_warns_when_a_tier_missing() -> None:
    """spec §25.1 — A=None triggers the explicit warning line."""
    plan = TieredPlan(
        run_date="2026-05-25", day_chaos=8, chaos_band="平静",
        tiers=[None, None, None, None],
        recommended_single=None,
    )
    out = render_tiered_plan(plan)
    assert "A 档因无 ≤1.65 真热门、或总赔率超 5.5 上限，今晚不出" in out


def test_render_warns_when_e_tier_missing() -> None:
    """spec §25.2.a — E=None triggers the cross-tier-dedup warning."""
    plan = TieredPlan(
        run_date="2026-05-25", day_chaos=8, chaos_band="平静",
        tiers=[None, None, None, None],
        recommended_single=None,
    )
    out = render_tiered_plan(plan)
    assert "E 档因跨档去重后剩余腿 < 4，今晚不出" in out
