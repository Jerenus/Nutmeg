"""Tests for jczq_today — spec §32 单一决策入口决策包。"""
from __future__ import annotations

from nutmeg.services.jczq_bold_combos import BoldLeg, BoldMatch
from nutmeg.services.jczq_tiered import (
    DEFAULT_TIER_A,
    DEFAULT_TIER_B,
    LegReason,
    Tier,
    TieredLeg,
    TieredPlan,
    confidence_tag_for_code,
)
from nutmeg.services.jczq_today import (
    classify_heat,
    derive_judgment_questions,
    render_today_packet,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _match(no: str, *, home_odds: float, away_odds: float = 6.0, draw: float = 3.5) -> BoldMatch:
    return BoldMatch(
        match_no=no,
        league="L",
        home=f"H{no}",
        away=f"A{no}",
        tc_odds={"home": home_odds, "draw": draw, "away": away_odds},
    )


def _leg(match_no: str, market: str, pick_label: str, odds: float) -> BoldLeg:
    pick = {
        "胜": "home", "平": "draw", "负": "away",
        "让胜": "home", "让平": "draw", "让负": "away",
    }.get(pick_label, pick_label)
    return BoldLeg(
        match_no=match_no, league="L", home=f"H{match_no}", away=f"A{match_no}",
        pick=pick, tc_odds=odds, boldness=0.8, reason="x",
        market=market, pick_label=pick_label,
    )


def _tier(profile, legs: list[BoldLeg], total_odds: float) -> Tier:
    return Tier(
        profile=profile,
        legs=[TieredLeg(lg, LegReason("m", "k", "p")) for lg in legs],
        total_odds=total_odds,
        stake_yuan=profile.base_stake_yuan,
        confidence_tag=confidence_tag_for_code(profile.code),
    )


def _plan(tiers, *, recommended=None, ttg_pool_empty=False) -> TieredPlan:
    return TieredPlan(
        run_date="2026-06-04", day_chaos=10, chaos_band="平静",
        tiers=tiers, recommended_single=recommended,
        ttg_pool_empty=ttg_pool_empty,
    )


# ---------------------------------------------------------------------------
# classify_heat — spec §32.3 boundaries
# ---------------------------------------------------------------------------


def test_heat_hard_at_150() -> None:
    assert classify_heat(_match("1", home_odds=1.50)) == "硬热(短赔)"


def test_heat_soft_at_155() -> None:
    assert classify_heat(_match("1", home_odds=1.55)) == "软热"


def test_heat_soft_at_210() -> None:
    assert classify_heat(_match("1", home_odds=2.10)) == "软热"


def test_heat_soft_mid_band() -> None:
    assert classify_heat(_match("1", home_odds=1.85)) == "软热"


def test_heat_coinflip_when_three_way_close() -> None:
    # favourite > 2.10 且三方接近
    m = _match("1", home_odds=2.60, away_odds=2.70, draw=3.10)
    assert classify_heat(m) == "coinflip"


def test_heat_plain_when_favourite_high_but_spread_wide() -> None:
    m = _match("1", home_odds=2.40, away_odds=8.0, draw=3.4)
    assert classify_heat(m) == "普通"


def test_heat_empty_when_no_had() -> None:
    m = BoldMatch(match_no="1", league="L", home="H", away="A", tc_odds={})
    assert classify_heat(m) == ""


# ---------------------------------------------------------------------------
# derive_judgment_questions — spec §32.4
# ---------------------------------------------------------------------------


def test_all_empty_asks_only_skip() -> None:
    plan = _plan([None, None, None, None])
    qs = derive_judgment_questions(plan, [])
    assert [q.q_id for q in qs] == ["Q_ALL_EMPTY"]
    assert "空仓" in qs[0].default


def test_a_empty_but_b_fired_asks_a_empty() -> None:
    b = _tier(DEFAULT_TIER_B, [_leg("M1", "hhad", "让胜", 3.5)], total_odds=40.0)
    plan = _plan([None, b, None, None], recommended="B")
    qids = {q.q_id for q in derive_judgment_questions(plan, [_match("M1", home_odds=2.6)])}
    assert "Q_A_EMPTY" in qids
    assert "Q_ALL_EMPTY" not in qids


def test_b_degraded_when_ttg_empty_and_b_fired() -> None:
    b = _tier(DEFAULT_TIER_B, [_leg("M1", "hhad", "让胜", 3.5)], total_odds=40.0)
    plan = _plan([None, b, None, None], recommended="B", ttg_pool_empty=True)
    qids = {q.q_id for q in derive_judgment_questions(plan, [_match("M1", home_odds=2.6)])}
    assert "Q_B_DEGRADED" in qids


def test_no_b_degraded_when_b_empty() -> None:
    plan = _plan([None, None, None, None], ttg_pool_empty=True)
    qids = {q.q_id for q in derive_judgment_questions(plan, [])}
    assert "Q_B_DEGRADED" not in qids


def test_softhot_leg_in_ticket_is_asked() -> None:
    a = _tier(DEFAULT_TIER_A, [_leg("M9", "had", "胜", 1.80)], total_odds=1.80)
    plan = _plan([a, None, None, None], recommended="A")
    matches = [_match("M9", home_odds=1.80)]  # 软热
    qs = derive_judgment_questions(plan, matches)
    soft = [q for q in qs if q.kind == "SOFTHOT"]
    assert len(soft) == 1
    assert soft[0].q_id == "Q_SOFTHOT_M9"
    assert "M9" in soft[0].match_no


def test_softhot_match_not_in_ticket_is_not_asked() -> None:
    a = _tier(DEFAULT_TIER_A, [_leg("M1", "had", "胜", 1.30)], total_odds=1.30)
    plan = _plan([a, None, None, None], recommended="A")
    # M9 is soft-hot but NOT in any tier → must not be asked
    matches = [_match("M1", home_odds=1.30), _match("M9", home_odds=1.80)]
    qids = {q.q_id for q in derive_judgment_questions(plan, matches)}
    assert "Q_SOFTHOT_M9" not in qids


def test_hardhot_leg_in_ticket_is_not_softhot_asked() -> None:
    a = _tier(DEFAULT_TIER_A, [_leg("M1", "had", "胜", 1.30)], total_odds=1.30)
    plan = _plan([a, None, None, None], recommended="A")
    qids = {q.q_id for q in derive_judgment_questions(plan, [_match("M1", home_odds=1.30)])}
    assert not any(qid.startswith("Q_SOFTHOT") for qid in qids)


# ---------------------------------------------------------------------------
# render_today_packet — spec §32.2
# ---------------------------------------------------------------------------


def test_packet_has_instruction_header_and_sections() -> None:
    a = _tier(DEFAULT_TIER_A, [_leg("M1", "had", "胜", 1.30)], total_odds=1.30)
    plan = _plan([a, None, None, None], recommended="A")
    out = render_today_packet(plan, [_match("M1", home_odds=1.30)], {})
    assert "钉死指令" in out
    assert "勿改腿" in out
    assert "## A. 引擎票面" in out
    assert "稳健底仓" in out  # render_tiered_plan embedded
    assert "## B. 盘面底座" in out
    assert "### B1 热度分层" in out
    assert "## C. 裁量问题" in out


def test_packet_poisson_positive_list() -> None:
    a = _tier(DEFAULT_TIER_A, [_leg("M1", "had", "胜", 1.30)], total_odds=1.30)
    plan = _plan([a, None, None, None], recommended="A")
    idx = {("M1", "had", "胜"): 0.12, ("M2", "ttg", "3球"): 0.01}
    out = render_today_packet(plan, [_match("M1", home_odds=1.30)], idx)
    assert "+12.0%" in out
    assert "1.0%" not in out  # below +5% floor, excluded


def test_packet_poisson_empty_list() -> None:
    a = _tier(DEFAULT_TIER_A, [_leg("M1", "had", "胜", 1.30)], total_odds=1.30)
    plan = _plan([a, None, None, None], recommended="A")
    out = render_today_packet(plan, [_match("M1", home_odds=1.30)], {})
    assert "今日无 ≥ +5% edge 的腿" in out


def test_packet_no_questions_shows_explicit_notice() -> None:
    a = _tier(DEFAULT_TIER_A, [_leg("M1", "had", "胜", 1.30)], total_odds=1.30)
    plan = _plan([a, None, None, None], recommended="A")
    out = render_today_packet(plan, [_match("M1", home_odds=1.30)], {})
    assert "今日无裁量问题" in out


def test_packet_questions_render_schema() -> None:
    plan = _plan([None, None, None, None])
    out = render_today_packet(plan, [], {})
    assert "Q_ALL_EMPTY" in out
    assert "confidence(1-5)" in out
    assert "| Q_ALL_EMPTY |" in out


def test_packet_no_banned_edge_words_for_bde() -> None:
    # B/D/E 零 edge 定调：packet 不得把 B/D/E 描述成搏 edge。
    a = _tier(DEFAULT_TIER_A, [_leg("M1", "had", "胜", 1.30)], total_odds=1.30)
    plan = _plan([a, None, None, None], recommended="A")
    out = render_today_packet(plan, [_match("M1", home_odds=1.30)], {})
    assert "零 edge" in out and "方差娱乐" in out
