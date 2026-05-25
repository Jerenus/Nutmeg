"""Tests for the bold-combo engine (`nutmeg/services/jczq_bold_combos.py`).

An ENTERTAINMENT-purpose JCZQ parlay generator — no predictive model, no edge.
These tests pin the five board signals, the boldness composition, the day
chaos value, the combination generator, and — critically — the welded honest
label + the no-advantage-wording acceptance assertions (spec §7).
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

from nutmeg.services.jczq_bold_combos import (
    ANCHOR_GAP_THRESHOLD,
    BALANCED_DAY_MAX,
    EQUIV_INDEPENDENT_LOW_THRESHOLD,
    FLIP_READING_CHAOS_MAX,
    HARD_LABEL,
    HEAVY_FAVORITE_DAY_MAX,
    OUTCOMES,
    POOL_MAX,
    POOL_MIN,
    THEME_DRAW_RESONANCE,
    THEME_HIGH_GOALS_RESONANCE,
    BoldComboEngine,
    BoldComboPlan,
    BoldLeg,
    BoldMatch,
    BoldTicket,
    MatchSignals,
    PoolSignals,
    anchor_ticket,
    bold_combos,
    bold_leg,
    boldness,
    chaos_band,
    chaos_pool_size,
    compute_pool_signals,
    conflict_score,
    contrarian_score,
    day_chaos,
    degenerate_pool_notice,
    dispersion_score,
    drift_score,
    equivalent_independent_tickets,
    flip_reading_hint,
    heat_score,
    pool_consensus,
    render_bold_plan,
    same_match_contradictions,
    theme_dissonance_notices,
)


def _match(
    *,
    match_no: str = "周日001",
    tc_odds: dict[str, float] | None = None,
    euro_odds: dict[str, float] | None = None,
    euro_opening: dict[str, float] | None = None,
    per_book_odds: dict[str, list[float]] | None = None,
    euro_fair_prob: dict[str, float] | None = None,
    tags: set[str] | None = None,
    vig: float = 0.13,
) -> BoldMatch:
    """A synthetic ``BoldMatch`` with sensible defaults for signal tests."""
    return BoldMatch(
        match_no=match_no,
        league="测试联赛",
        home="主队",
        away="客队",
        tc_odds=tc_odds or {"home": 2.0, "draw": 3.3, "away": 3.5},
        euro_odds=euro_odds or {},
        euro_opening=euro_opening or {},
        per_book_odds=per_book_odds or {},
        euro_fair_prob=euro_fair_prob or {},
        tags=tags or set(),
        vig=vig,
    )


# ---------------------------------------------------------------------------
# Task 2 — the five board-signal scoring functions
# ---------------------------------------------------------------------------


def test_outcomes_vocabulary() -> None:
    assert OUTCOMES == ("home", "draw", "away")


def test_conflict_score_is_absolute_fair_prob_gap() -> None:
    tc_fair = {"home": 0.30, "draw": 0.35, "away": 0.35}
    euro_fair = {"home": 0.45, "draw": 0.30, "away": 0.25}

    score = conflict_score(tc_fair, euro_fair)

    assert math.isclose(score["home"], 0.15, abs_tol=1e-9)
    assert math.isclose(score["draw"], 0.05, abs_tol=1e-9)
    assert math.isclose(score["away"], 0.10, abs_tol=1e-9)


def test_conflict_score_clips_to_unit_interval() -> None:
    score = conflict_score(
        {"home": 0.99, "draw": 0.005, "away": 0.005},
        {"home": 0.0, "draw": 0.5, "away": 0.5},
    )
    assert all(0.0 <= v <= 1.0 for v in score.values())


def test_conflict_score_degrades_to_zero_without_euro() -> None:
    """Missing 欧赔 → empty euro_fair → conflict signal is 0, never a crash."""
    score = conflict_score({"home": 0.4, "draw": 0.3, "away": 0.3}, {})
    assert score == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_contrarian_score_rewards_non_favorite_outcomes() -> None:
    tc_fair = {"home": 0.55, "draw": 0.25, "away": 0.20}

    score = contrarian_score(tc_fair)

    assert score["home"] == 0.0  # 体彩 favorite — never contrarian
    assert math.isclose(score["draw"], 0.75, abs_tol=1e-9)
    assert math.isclose(score["away"], 0.80, abs_tol=1e-9)


def test_drift_score_measures_implied_probability_movement() -> None:
    opening = {"home": 2.0, "draw": 3.4, "away": 3.4}
    live = {"home": 1.6, "draw": 3.4, "away": 3.4}

    score = drift_score(opening, live)

    assert score["home"] > 0.0  # the market moved on home
    assert score["draw"] == 0.0  # unchanged
    assert score["away"] == 0.0
    assert all(0.0 <= v <= 1.0 for v in score.values())


def test_drift_score_degrades_to_zero_without_opening() -> None:
    score = drift_score({}, {"home": 1.6, "draw": 3.4, "away": 3.4})
    assert score == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_dispersion_score_zero_when_books_agree() -> None:
    per_book = {
        "home": [2.0, 2.0, 2.0],
        "draw": [3.3, 3.3, 3.3],
        "away": [3.5, 3.5, 3.5],
    }
    score = dispersion_score(per_book)
    assert score == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_dispersion_score_positive_when_books_disagree() -> None:
    per_book = {
        "home": [1.5, 2.0, 2.8],
        "draw": [3.3, 3.3, 3.3],
        "away": [3.5, 3.5, 3.5],
    }
    score = dispersion_score(per_book)
    assert score["home"] > 0.0
    assert score["draw"] == 0.0
    assert all(0.0 <= v <= 1.0 for v in score.values())


def test_dispersion_score_degrades_to_zero_without_books() -> None:
    score = dispersion_score({})
    assert score == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_heat_score_combines_tags_and_vig() -> None:
    from nutmeg.services.jczq_bold_combos import HEAT_TAG, HEAT_VIG_GAIN

    score = heat_score({"强胆场", "hi-vol"}, vig=0.13)

    expected = 2 * HEAT_TAG + (0.13 - 0.12) * HEAT_VIG_GAIN
    assert math.isclose(score, min(expected, 1.0), abs_tol=1e-9)


def test_heat_score_ignores_unknown_tags_and_clips() -> None:
    score = heat_score({"not-a-real-tag"}, vig=0.0)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Task 3 — boldness composition + bold-leg selection
# ---------------------------------------------------------------------------


def test_boldness_combines_five_signals_per_outcome() -> None:
    match = _match()

    score = boldness(match)

    assert set(score) == {"home", "draw", "away"}
    assert all(isinstance(v, float) for v in score.values())


def test_boldness_rewards_a_contrarian_well_conflicted_outcome() -> None:
    """An away pick that is contrarian (体彩 home favorite) AND where 欧赔
    strongly disagrees should out-score the bland 体彩 favorite."""
    match = _match(
        tc_odds={"home": 1.7, "draw": 3.6, "away": 5.0},
        euro_odds={"home": 3.0, "draw": 3.4, "away": 2.3},
    )

    score = boldness(match)

    assert score["away"] > score["home"]


def test_bold_leg_picks_the_top_boldness_outcome_with_reason() -> None:
    match = _match(
        match_no="周日007",
        tc_odds={"home": 1.6, "draw": 3.8, "away": 6.0},
        euro_odds={"home": 3.2, "draw": 3.3, "away": 2.2},
    )

    leg = bold_leg(match)

    assert isinstance(leg, BoldLeg)
    assert leg.match_no == "周日007"
    assert leg.pick == "away"
    assert leg.tc_odds == 6.0  # the 体彩 odds for the chosen pick
    assert leg.boldness > 0.0
    assert isinstance(leg.reason, str) and leg.reason  # human-readable reason
    # The reason names the dominant board signal driving this pick.
    assert "主导信号" in leg.reason


def test_bold_leg_reason_names_the_largest_signal_contribution() -> None:
    """The 大胆理由 names whichever signal contributes most to the chosen pick.

    Construct a match where 欧赔 exactly mirrors 体彩 (conflict = 0) and 欧赔
    did not move (drift = 0) and books agree (dispersion = 0): then contrarian
    is the only non-heat signal, so the reason must name 反直觉冷门."""
    match = _match(
        match_no="周日011",
        tc_odds={"home": 1.6, "draw": 3.8, "away": 6.0},
        euro_odds={"home": 1.6, "draw": 3.8, "away": 6.0},
        euro_opening={"home": 1.6, "draw": 3.8, "away": 6.0},
        per_book_odds={
            "home": [1.6, 1.6],
            "draw": [3.8, 3.8],
            "away": [6.0, 6.0],
        },
        tags=set(),
        vig=0.12,
    )

    leg = bold_leg(match)

    assert leg.pick == "away"  # the coldest non-favorite — contrarian-driven
    assert "反直觉冷门" in leg.reason


# ---------------------------------------------------------------------------
# Task 4 — day-level chaos value
# ---------------------------------------------------------------------------


def _calm_match(match_no: str) -> BoldMatch:
    """A match with no conflict and books in lockstep — low uncertainty."""
    odds = {"home": 2.0, "draw": 3.3, "away": 3.5}
    return _match(
        match_no=match_no,
        tc_odds=odds,
        euro_odds=odds,
        euro_opening=odds,
        per_book_odds={o: [odds[o], odds[o], odds[o]] for o in OUTCOMES},
    )


def _wild_match(match_no: str) -> BoldMatch:
    """A match with a huge 体彩-vs-欧赔 gap and widely-spread books."""
    return _match(
        match_no=match_no,
        tc_odds={"home": 2.0, "draw": 3.3, "away": 3.5},
        euro_odds={"home": 6.0, "draw": 4.0, "away": 1.4},
        euro_opening={"home": 6.0, "draw": 4.0, "away": 1.4},
        per_book_odds={
            "home": [3.0, 6.0, 12.0],
            "draw": [2.5, 4.0, 7.0],
            "away": [1.2, 1.4, 1.9],
        },
    )


def test_day_chaos_low_for_calm_matches() -> None:
    matches = [_calm_match(f"周日{i:03d}") for i in range(1, 6)]
    assert day_chaos(matches) <= 5


def test_day_chaos_high_for_wild_matches() -> None:
    matches = [_wild_match(f"周日{i:03d}") for i in range(1, 6)]
    assert day_chaos(matches) >= 60


def test_day_chaos_clamped_to_0_100() -> None:
    assert 0 <= day_chaos([_calm_match("周日001")]) <= 100
    assert 0 <= day_chaos([_wild_match("周日001")]) <= 100
    assert day_chaos([]) == 0


def test_chaos_pool_size_maps_chaos_to_candidate_pool() -> None:
    assert chaos_pool_size(0) == POOL_MIN
    assert chaos_pool_size(100) == POOL_MAX
    mid = chaos_pool_size(50)
    assert POOL_MIN <= mid <= POOL_MAX


def test_chaos_band_labels() -> None:
    assert chaos_band(5) == "平静"
    assert chaos_band(50) == "中等"
    assert chaos_band(90) == "混乱"


# ---------------------------------------------------------------------------
# Task 5 — combination generation + 稳健底仓
# ---------------------------------------------------------------------------


def _legs(count: int) -> list[BoldLeg]:
    """A pool of ``count`` distinct-match bold legs with varied odds."""
    return [
        BoldLeg(
            match_no=f"周日{i:03d}",
            league="测试联赛",
            home=f"主{i}",
            away=f"客{i}",
            pick="away",
            tc_odds=2.0 + 0.5 * i,
            boldness=0.3 + 0.05 * i,
            reason="负向 · 主导信号「反直觉冷门」",
        )
        for i in range(1, count + 1)
    ]


def test_bold_combos_generates_3_4_5_fold_tickets() -> None:
    tickets = bold_combos(_legs(6), chaos=50)

    assert tickets
    for ticket in tickets:
        assert isinstance(ticket, BoldTicket)
        assert ticket.fold in (3, 4, 5)
        assert len(ticket.legs) == ticket.fold


def test_bold_combos_legs_are_distinct_matches_rule_o() -> None:
    for ticket in bold_combos(_legs(6), chaos=50):
        match_nos = [leg.match_no for leg in ticket.legs]
        assert len(match_nos) == len(set(match_nos))


def test_bold_combos_total_odds_is_product_of_leg_odds() -> None:
    for ticket in bold_combos(_legs(6), chaos=50):
        product = 1.0
        for leg in ticket.legs:
            product *= leg.tc_odds
        assert math.isclose(ticket.total_odds, product, rel_tol=1e-9)


def test_bold_combos_ranked_by_band_fit_times_avg_boldness() -> None:
    """Tickets are ordered by band-fit × 大胆分 — realistic-odds combos rank
    first, not raw-odds moonshots (spec §13)."""
    from nutmeg.services.jczq_bold_combos import _ticket_rank_score

    tickets = bold_combos(_legs(6), chaos=50)
    scores = [_ticket_rank_score(t.legs) for t in tickets]
    assert scores == sorted(scores, reverse=True)


def test_bold_combos_empty_when_too_few_legs() -> None:
    assert bold_combos(_legs(2), chaos=50) == []


# ---------------------------------------------------------------------------
# spec §24 — theme soft-retirement (the 17.3 meta-rule's second half)
# ---------------------------------------------------------------------------


def test_min_theme_legs_for_retirement_is_30() -> None:
    """spec §17.3/§24 — the 30-leg threshold is a named constant, not magic."""
    from nutmeg.services.jczq_bold_combos import MIN_THEME_LEGS_FOR_RETIREMENT
    assert MIN_THEME_LEGS_FOR_RETIREMENT == 30


def test_retired_themes_from_history_5_24_case_triggers() -> None:
    """spec §24 — 5/24 cumulative state: 平局收割 = 23 tickets / 0 hits /
    69 graded legs → past 30-leg gate with zero hits → returns {'平局收割'}."""
    from nutmeg.services.jczq_bold_combos import retired_themes_from_history

    by_theme = {
        "平局收割": {"tickets": 23, "ticket_hits": 0, "legs": 69, "leg_hits": 11},
    }
    assert retired_themes_from_history(by_theme) == frozenset({"平局收割"})


def test_retired_themes_below_threshold_keeps_theme() -> None:
    """spec §24 — fewer than 30 graded legs → not retired even at 0 hits.
    5/20 state: 平局收割 9 tickets × 3 = 27 graded legs, still under 30."""
    from nutmeg.services.jczq_bold_combos import retired_themes_from_history

    by_theme = {
        "平局收割": {"tickets": 9, "ticket_hits": 0, "legs": 27, "leg_hits": 5},
    }
    assert retired_themes_from_history(by_theme) == frozenset()


def test_retired_themes_one_hit_above_threshold_keeps_theme() -> None:
    """spec §24 — strict zero-ticket-hits gate. ticket_hits > 0 keeps the theme
    even past 30 legs (gives the theme room to recover — user prefers '在困难
    中找落足点' over wholesale theme deletion)."""
    from nutmeg.services.jczq_bold_combos import retired_themes_from_history

    by_theme = {
        "平局收割": {"tickets": 35, "ticket_hits": 1, "legs": 100, "leg_hits": 12},
    }
    assert retired_themes_from_history(by_theme) == frozenset()


def test_retired_themes_handles_legacy_slot_without_legs_key() -> None:
    """spec §24 — legacy by_theme slot (no ``legs`` field) defaults to 0 legs →
    never retired. Forces explicit history backfill before retirement can fire."""
    from nutmeg.services.jczq_bold_combos import retired_themes_from_history

    by_theme = {"平局收割": {"tickets": 23, "ticket_hits": 0}}
    assert retired_themes_from_history(by_theme) == frozenset()


def test_retired_themes_multiple_themes_in_one_pass() -> None:
    """spec §24 — multiple themes can be retired in the same accumulator pass."""
    from nutmeg.services.jczq_bold_combos import retired_themes_from_history

    by_theme = {
        "平局收割": {"tickets": 23, "ticket_hits": 0, "legs": 69, "leg_hits": 4},
        "冷门比分梦": {"tickets": 12, "ticket_hits": 0, "legs": 36, "leg_hits": 2},
        "全市场混搭": {"tickets": 5, "ticket_hits": 0, "legs": 15, "leg_hits": 1},
    }
    assert retired_themes_from_history(by_theme) == frozenset(
        {"平局收割", "冷门比分梦"}
    )


def test_bold_combos_retired_themes_default_empty_keeps_backcompat() -> None:
    """spec §24 — calling bold_combos without retired_themes (or with an empty
    set) yields identical tickets to the pre-§24 behavior."""
    legs = _legs(6)
    pre = bold_combos(legs, chaos=50)
    post = bold_combos(legs, chaos=50, retired_themes=frozenset())
    assert [(t.fold, [lg.match_no for lg in t.legs]) for t in pre] == [
        (t.fold, [lg.match_no for lg in t.legs]) for t in post
    ]


def test_bold_combos_phase_a_skips_retired_theme(monkeypatch) -> None:
    """spec §24 — passing retired_themes={'平局收割'} drops the Phase A
    guaranteed slot for that theme.

    Phase B may still pick draw-majority combos on score+penalty alone
    (§24 by design: Phase B unchanged). To isolate the Phase A skip
    cleanly, we monkeypatch ``BOLD_TICKET_COUNT`` to 2 so Phase B's
    while-loop never fires for the baseline (Phase A's 2 themes already
    fill the budget); the only thing the retired set can change is
    whether Phase A reserved a draw slot.

    Pool: 2 draw legs + 5 higher-boldness non-draw legs → only 2 themes
    present (平局收割 + 全市场混搭). Baseline → Phase A picks 1 of each =
    2 tickets, one is 平局收割. Retired → Phase A picks only 全市场混搭
    = 1 ticket, plus Phase B fills 1 more (best score+penalty = a
    non-draw combo). Result: 平局收割 count drops 1 → 0.
    """
    from nutmeg.services import jczq_bold_combos as bc_mod
    from nutmeg.services.jczq_bold_combos import ticket_theme

    monkeypatch.setattr(bc_mod, "BOLD_TICKET_COUNT", 2)

    draw_legs = [
        BoldLeg(
            match_no=f"周日{i:03d}", league="L", home=f"H{i}", away=f"A{i}",
            pick="draw", tc_odds=3.5, boldness=0.30 + 0.02 * i,
            reason="r", market="had", pick_label="平",
        )
        for i in range(1, 3)
    ]
    away_legs = [
        BoldLeg(
            match_no=f"周日{i + 2:03d}", league="L", home=f"H{i + 2}",
            away=f"A{i + 2}",
            pick="away", tc_odds=2.5, boldness=0.55 + 0.02 * i,
            reason="r", market="had", pick_label="负",
        )
        for i in range(1, 6)
    ]
    legs = draw_legs + away_legs

    plain = bold_combos(legs, chaos=50)
    plain_themes = [ticket_theme(t.legs)[0] for t in plain]
    assert plain_themes.count("平局收割") == 1, (
        f"baseline: Phase A should reserve a 平局收割 slot, got {plain_themes}"
    )

    retired = bold_combos(
        legs, chaos=50, retired_themes=frozenset({"平局收割"})
    )
    retired_themes_out = [ticket_theme(t.legs)[0] for t in retired]
    assert "平局收割" not in retired_themes_out, (
        f"retired={{'平局收割'}}: no Phase A slot, "
        f"got {retired_themes_out}"
    )
    # Phase B fills the saved seat — ticket budget preserved.
    assert len(retired) == len(plain)


def test_anchor_ticket_picks_lowest_odds_favorites() -> None:
    matches = [
        _match(match_no="周日001", tc_odds={"home": 1.30, "draw": 4.5, "away": 8.0}),
        _match(match_no="周日002", tc_odds={"home": 1.45, "draw": 4.0, "away": 6.5}),
        _match(match_no="周日003", tc_odds={"home": 2.80, "draw": 3.1, "away": 2.5}),
        _match(match_no="周日004", tc_odds={"home": 1.60, "draw": 3.8, "away": 5.0}),
    ]

    anchor = anchor_ticket(matches)

    assert isinstance(anchor, BoldTicket)
    assert anchor.fold in (2, 3)
    # It anchors on the matches whose 体彩 favorite has the LOWEST odds.
    picked = {leg.match_no for leg in anchor.legs}
    assert "周日001" in picked  # 1.30 favorite
    assert "周日002" in picked  # 1.45 favorite
    assert "周日003" not in picked  # weakest favorite — excluded
    # Each anchor leg picks that match's 体彩 favorite (lowest-odds outcome).
    for leg in anchor.legs:
        assert leg.pick == "home"


# ---------------------------------------------------------------------------
# spec §17.1 — 体彩 vs 欧赔 implied-gap guard on the anchor (5/19 review)
# ---------------------------------------------------------------------------


def test_anchor_gap_threshold_constant() -> None:
    """spec §17.1 — the wall is +8pp."""
    assert ANCHOR_GAP_THRESHOLD == 0.08


def test_anchor_rejects_leg_when_tc_overprices_vs_euro_fair_prob() -> None:
    """spec §17.1 — 体彩 implied − 欧赔 公平 ≥ 8pp → leg dropped from anchor.

    周三010 fixture: tc home @1.17 (implied 85.5%) vs 欧赔 fair 71.5% → gap
    +14.0pp. The leg must NOT enter the anchor; a calmer fixture (gap < 8pp)
    in the same day still anchors normally.
    """
    matches = [
        # gap = 1/1.17 − 0.715 = 0.140 → REJECT
        _match(
            match_no="周三010",
            tc_odds={"home": 1.17, "draw": 5.00, "away": 9.42},
            euro_fair_prob={"home": 0.715, "draw": 0.186, "away": 0.099},
        ),
        # gap = 1/1.41 − 0.661 = 0.048 → KEEP
        _match(
            match_no="周三009",
            tc_odds={"home": 1.41, "draw": 4.18, "away": 7.99},
            euro_fair_prob={"home": 0.661, "draw": 0.222, "away": 0.116},
        ),
    ]
    anchor = anchor_ticket(matches)
    picked = {leg.match_no for leg in anchor.legs}
    assert "周三010" not in picked, "≥ 8pp gap leg must be dropped (§17.1)"
    assert "周三009" in picked, "gap < 8pp leg must still anchor (§17.1)"


def test_anchor_drops_all_three_overpriced_legs_5_20_live_case() -> None:
    """spec §17.1 — 5/20 live: all 3 anchor candidates trigger the guard;
    anchor should end up empty (degraded honestly, never crash)."""
    matches = [
        _match(
            match_no="周三002",
            tc_odds={"home": 9.97, "draw": 6.68, "away": 1.17},
            euro_fair_prob={"home": 0.093, "draw": 0.139, "away": 0.767},
        ),
        _match(
            match_no="周三005",
            tc_odds={"home": 1.25, "draw": 5.04, "away": 6.49},
            euro_fair_prob={"home": 0.672, "draw": 0.184, "away": 0.143},
        ),
        _match(
            match_no="周三010",
            tc_odds={"home": 1.17, "draw": 5.00, "away": 9.42},
            euro_fair_prob={"home": 0.715, "draw": 0.186, "away": 0.099},
        ),
    ]
    anchor = anchor_ticket(matches)
    assert anchor.legs == []
    assert anchor.fold == 0
    assert anchor.kind == "稳健底仓"


def test_anchor_at_threshold_boundary_is_rejected() -> None:
    """spec §17.1 — ≥ 0.08 triggers, so == 0.08 is rejected (inclusive)."""
    matches = [
        _match(
            match_no="周日001",
            tc_odds={"home": 1.25, "draw": 4.5, "away": 8.0},
            # 1/1.25 = 0.80, fair 0.72 → gap exactly 0.08 → REJECT
            euro_fair_prob={"home": 0.72, "draw": 0.18, "away": 0.10},
        ),
        _match(
            match_no="周日002",
            tc_odds={"home": 1.50, "draw": 4.0, "away": 6.0},
            # 1/1.50 = 0.667, fair 0.60 → gap 0.067 → KEEP
            euro_fair_prob={"home": 0.60, "draw": 0.25, "away": 0.15},
        ),
    ]
    anchor = anchor_ticket(matches)
    picked = {leg.match_no for leg in anchor.legs}
    assert "周日001" not in picked
    assert "周日002" in picked


def test_anchor_graceful_degrade_without_euro_fair_prob() -> None:
    """spec §17.1 — no 欧赔 snapshot → empty euro_fair_prob → guard skipped,
    anchor falls back to the v1 lowest-odds-favorite behaviour. Snapshot
    missing must never crash or empty the anchor."""
    matches = [
        _match(
            match_no="周日001",
            tc_odds={"home": 1.17, "draw": 5.0, "away": 9.5},
            euro_fair_prob={},  # no 欧赔 data
        ),
        _match(
            match_no="周日002",
            tc_odds={"home": 1.30, "draw": 4.5, "away": 8.0},
            euro_fair_prob={},
        ),
    ]
    anchor = anchor_ticket(matches)
    assert len(anchor.legs) == 2  # both anchored, v1 behaviour preserved


def test_anchor_guard_only_checks_favored_outcome() -> None:
    """spec §17.1 — gap is computed only for the favorite pick, not the
    whole match. A match with a benign favorite gap is kept even if other
    outcomes have wild gaps."""
    matches = [
        _match(
            match_no="周日001",
            # favorite = away @1.60 → implied 0.625, fair 0.60 → gap 0.025 KEEP
            # even though home gap (= 1/3.5 − 0.10 = 0.186) is wild.
            tc_odds={"home": 3.50, "draw": 4.0, "away": 1.60},
            euro_fair_prob={"home": 0.10, "draw": 0.30, "away": 0.60},
        ),
    ]
    anchor = anchor_ticket(matches)
    assert len(anchor.legs) == 1
    assert anchor.legs[0].pick == "away"


# ---------------------------------------------------------------------------
# spec §17.4 — 等效独立票数 — exposes "5 tickets ≠ 5 independent bets"
# ---------------------------------------------------------------------------


def _ticket(*, match_nos: tuple[str, ...]) -> BoldTicket:
    """Build a minimal BoldTicket with the given match numbers (one leg each)."""
    legs = [
        BoldLeg(
            match_no=mn,
            league="L",
            home="H",
            away="A",
            pick="home",
            tc_odds=3.0,
            boldness=0.4,
            reason="test",
            market="had",
            pick_label="胜",
        )
        for mn in match_nos
    ]
    return BoldTicket(
        id="大胆票X",
        kind="大胆票",
        legs=legs,
        fold=len(legs),
        total_odds=3.0 ** len(legs),
        avg_boldness=0.4,
        note="",
    )


def test_equivalent_independent_tickets_low_threshold_constant() -> None:
    """spec §17.4 — < 1.5 triggers the chaos-line suffix."""
    assert EQUIV_INDEPENDENT_LOW_THRESHOLD == 1.5


def test_equivalent_independent_tickets_5_19_case_is_1_25() -> None:
    """spec §17.4 — 5/19 day: 5 tickets, 16 legs, 4 unique matches.
    equiv = 4 / (16/5) = 1.25."""
    tickets = [
        _ticket(match_nos=("M1", "M2", "M3")),
        _ticket(match_nos=("M1", "M2", "M4")),
        _ticket(match_nos=("M1", "M3", "M4")),
        _ticket(match_nos=("M1", "M2", "M3", "M4")),
        _ticket(match_nos=("M2", "M3", "M4")),
    ]
    eq = equivalent_independent_tickets(tickets)
    assert math.isclose(eq, 1.25, abs_tol=1e-9)


def test_equivalent_independent_tickets_perfectly_diversified_is_one_per_ticket() -> None:
    """Fully disjoint tickets → equiv == ticket count."""
    tickets = [
        _ticket(match_nos=("M1", "M2", "M3")),
        _ticket(match_nos=("M4", "M5", "M6")),
        _ticket(match_nos=("M7", "M8", "M9")),
    ]
    # 9 unique / (9/3 mean) = 9 / 3 = 3.0
    eq = equivalent_independent_tickets(tickets)
    assert math.isclose(eq, 3.0, abs_tol=1e-9)


def test_equivalent_independent_tickets_zero_when_empty() -> None:
    """No tickets → 0.0 (renderer skips the line)."""
    assert equivalent_independent_tickets([]) == 0.0


def test_render_includes_equiv_independent_line() -> None:
    """spec §17.4 — render emits a 🟦 equiv-independent line below the
    concentration warning; phrasing has no banned words."""
    matches = [
        _match(match_no="周日001", tc_odds={"home": 1.30, "draw": 4.5, "away": 8.0}),
    ]
    tickets = [
        _ticket(match_nos=("周日001", "周日002", "周日003")),
        _ticket(match_nos=("周日001", "周日002", "周日004")),
        _ticket(match_nos=("周日001", "周日003", "周日004")),
        _ticket(match_nos=("周日001", "周日002", "周日003", "周日004")),
        _ticket(match_nos=("周日002", "周日003", "周日004")),
    ]
    plan = BoldComboPlan(
        run_date="2026-05-19",
        day_chaos=7,
        chaos_band="平静",
        anchor=anchor_ticket(matches),
        tickets=tickets,
        label=HARD_LABEL,
    )
    out = render_bold_plan(plan)
    assert "🟦 等效独立票数" in out
    assert "1.25" in out
    # 🎲 label legitimately contains "非 edge" — strip it before scanning.
    body = out[len(HARD_LABEL):]
    for word in _BANNED_WORDS:
        assert word not in body, f"advantage word leaked: {word}"


def test_render_skips_equiv_independent_line_when_no_tickets() -> None:
    plan = BoldComboPlan(
        run_date="2026-05-19",
        day_chaos=10,
        chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=[],
        label=HARD_LABEL,
    )
    out = render_bold_plan(plan)
    assert "等效独立票数" not in out


def test_chaos_line_adds_suffix_when_equiv_independent_below_1_5() -> None:
    """spec §17.4 — equiv < 1.5 → append '（高度共享场次）' to the chaos line."""
    tickets = [
        _ticket(match_nos=("M1", "M2", "M3")),
        _ticket(match_nos=("M1", "M2", "M4")),
        _ticket(match_nos=("M1", "M3", "M4")),
        _ticket(match_nos=("M1", "M2", "M3", "M4")),
        _ticket(match_nos=("M2", "M3", "M4")),
    ]
    plan = BoldComboPlan(
        run_date="2026-05-19",
        day_chaos=7,
        chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=tickets,
        label=HARD_LABEL,
    )
    out = render_bold_plan(plan)
    chaos_line = next(ln for ln in out.splitlines() if "混乱值" in ln)
    assert "高度共享场次" in chaos_line


def test_chaos_line_no_suffix_when_equiv_independent_above_1_5() -> None:
    """Fully diversified → chaos line stays clean (no suffix)."""
    tickets = [
        _ticket(match_nos=("M1", "M2", "M3")),
        _ticket(match_nos=("M4", "M5", "M6")),
        _ticket(match_nos=("M7", "M8", "M9")),
    ]
    plan = BoldComboPlan(
        run_date="2026-05-19",
        day_chaos=7,
        chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=tickets,
        label=HARD_LABEL,
    )
    out = render_bold_plan(plan)
    chaos_line = next(ln for ln in out.splitlines() if "混乱值" in ln)
    assert "高度共享场次" not in chaos_line


# ---------------------------------------------------------------------------
# spec §18 — degenerate-pool notice — 5/20 review (single-leg-per-match
# bold pool → "5 themed tickets" are really C(N,k) enumeration)
# ---------------------------------------------------------------------------


def _typed_leg(
    *, match_no: str, market: str = "had", pick_label: str = "胜",
) -> BoldLeg:
    """Build a BoldLeg with explicit (match_no, market, pick_label) — the
    triple §18 uses to count distinct legs in the bold pool."""
    return BoldLeg(
        match_no=match_no,
        league="L",
        home="H",
        away="A",
        pick="home",
        tc_odds=3.0,
        boldness=0.4,
        reason="test",
        market=market,
        pick_label=pick_label,
    )


def _typed_ticket(legs: list[BoldLeg]) -> BoldTicket:
    """A BoldTicket from explicit legs (so a match can contribute >1 distinct leg)."""
    return BoldTicket(
        id="大胆票X",
        kind="大胆票",
        legs=legs,
        fold=len(legs),
        total_odds=3.0 ** len(legs),
        avg_boldness=0.4,
        note="",
    )


def test_degenerate_pool_notice_5_20_case_full_enumeration() -> None:
    """spec §18 — 5/20 live: 4-match pool × 1 leg/match, 5 tickets =
    C(4,3) + C(4,4) = 5 — the full enumeration of all ≥3-leg combinations
    of the 4-match pool. Notice should fire with match count + folds."""
    L = {
        m: _typed_leg(match_no=m, market="crs", pick_label="1:1")
        for m in ("M1", "M2", "M3", "M4")
    }
    tickets = [
        _typed_ticket([L["M1"], L["M2"], L["M3"]]),
        _typed_ticket([L["M1"], L["M2"], L["M4"]]),
        _typed_ticket([L["M1"], L["M3"], L["M4"]]),
        _typed_ticket([L["M2"], L["M3"], L["M4"]]),
        _typed_ticket([L["M1"], L["M2"], L["M3"], L["M4"]]),
    ]
    notice = degenerate_pool_notice(tickets)
    assert notice != ""
    assert "腿池退化" in notice
    assert "4 场池" in notice
    assert "5 张" in notice
    assert "C(4,3)" in notice and "C(4,4)" in notice
    assert "共 5 种" in notice  # full enumeration


def test_degenerate_pool_notice_partial_enumeration() -> None:
    """spec §18 — same 4-match × 1-leg pool, only 3 tickets out of 5 possible
    → notice still fires, marked as partial '3/5'."""
    L = {
        m: _typed_leg(match_no=m, market="crs", pick_label="1:0")
        for m in ("M1", "M2", "M3", "M4")
    }
    tickets = [
        _typed_ticket([L["M1"], L["M2"], L["M3"]]),
        _typed_ticket([L["M1"], L["M2"], L["M4"]]),
        _typed_ticket([L["M1"], L["M2"], L["M3"], L["M4"]]),
    ]
    notice = degenerate_pool_notice(tickets)
    assert notice != ""
    assert "腿池退化" in notice
    assert "3 张" in notice
    assert "3/5" in notice  # partial enumeration


def test_degenerate_pool_notice_does_not_fire_when_match_has_multiple_legs() -> None:
    """spec §18 — a match contributing 2 distinct legs (different market/pick)
    means the pool is NOT degenerate; theme grouping is doing real work."""
    legs_by_id = {
        "M1_a": _typed_leg(match_no="M1", market="crs", pick_label="1:1"),
        "M1_b": _typed_leg(match_no="M1", market="had", pick_label="平"),
        "M2": _typed_leg(match_no="M2", market="hhad", pick_label="让平"),
        "M3": _typed_leg(match_no="M3", market="crs", pick_label="0:0"),
        "M4": _typed_leg(match_no="M4", market="ttg", pick_label="2球"),
    }
    tickets = [
        _typed_ticket([legs_by_id["M1_a"], legs_by_id["M2"], legs_by_id["M3"]]),
        _typed_ticket([legs_by_id["M1_b"], legs_by_id["M2"], legs_by_id["M4"]]),
        _typed_ticket([legs_by_id["M1_a"], legs_by_id["M3"], legs_by_id["M4"]]),
    ]
    notice = degenerate_pool_notice(tickets)
    assert notice == ""


def test_degenerate_pool_notice_does_not_fire_on_single_ticket() -> None:
    """spec §18 — needs ≥ 2 tickets to talk about enumeration."""
    L = _typed_leg(match_no="M1")
    tickets = [_typed_ticket([L])]
    assert degenerate_pool_notice(tickets) == ""


def test_degenerate_pool_notice_does_not_fire_on_empty() -> None:
    assert degenerate_pool_notice([]) == ""


def test_render_includes_degenerate_pool_notice_below_equiv_independent_line() -> None:
    """spec §18 — the notice is rendered immediately below the §17.4
    equivalent-independent line; phrasing carries no banned words."""
    L = {
        m: _typed_leg(match_no=m, market="crs", pick_label="1:1")
        for m in ("M1", "M2", "M3", "M4")
    }
    tickets = [
        _typed_ticket([L["M1"], L["M2"], L["M3"]]),
        _typed_ticket([L["M1"], L["M2"], L["M4"]]),
        _typed_ticket([L["M1"], L["M3"], L["M4"]]),
        _typed_ticket([L["M2"], L["M3"], L["M4"]]),
        _typed_ticket([L["M1"], L["M2"], L["M3"], L["M4"]]),
    ]
    plan = BoldComboPlan(
        run_date="2026-05-20",
        day_chaos=8,
        chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=tickets,
        label=HARD_LABEL,
    )
    out = render_bold_plan(plan)
    lines = out.splitlines()
    equiv_idx = next(i for i, ln in enumerate(lines) if "等效独立票数" in ln)
    notice_idx = next(i for i, ln in enumerate(lines) if "腿池退化" in ln)
    assert notice_idx == equiv_idx + 1, "退化标签必须紧跟在等效独立票数行下方"
    body = out[len(HARD_LABEL):]
    for word in _BANNED_WORDS:
        assert word not in body, f"advantage word leaked: {word}"


def test_retired_themes_with_stats_returns_sorted_records() -> None:
    """spec §24 — retired_themes_with_stats turns a cumulative by_theme dict
    into a tuple of RetiredTheme records, sorted by ticket count desc so the
    biggest underperformer shows first."""
    from nutmeg.services.jczq_bold_combos import (
        RetiredTheme,
        retired_themes_with_stats,
    )

    by_theme = {
        "平局收割": {"tickets": 23, "ticket_hits": 0, "legs": 69, "leg_hits": 11},
        "冷门比分梦": {"tickets": 12, "ticket_hits": 0, "legs": 36, "leg_hits": 2},
        "全市场混搭": {"tickets": 5, "ticket_hits": 0, "legs": 15, "leg_hits": 1},
    }
    out = retired_themes_with_stats(by_theme)
    assert out == (
        RetiredTheme(theme="平局收割", tickets=23, ticket_hits=0,
                     legs=69, leg_hits=11),
        RetiredTheme(theme="冷门比分梦", tickets=12, ticket_hits=0,
                     legs=36, leg_hits=2),
    )


def test_retired_themes_with_stats_empty_when_no_history() -> None:
    """spec §24 — empty/missing history → empty tuple, never a crash."""
    from nutmeg.services.jczq_bold_combos import retired_themes_with_stats

    assert retired_themes_with_stats({}) == ()
    assert retired_themes_with_stats(None) == ()


def test_render_includes_retirement_notice_below_theme_dissonance() -> None:
    """spec §24 — when ``plan.retired_themes`` is non-empty, render one
    notice line per retired theme. Position: between §21 dissonance notices
    and the blank line before ``## 稳健底仓``. Phrasing carries no banned
    words."""
    from nutmeg.services.jczq_bold_combos import RetiredTheme

    plan = BoldComboPlan(
        run_date="2026-05-25",
        day_chaos=8,
        chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=[],
        label=HARD_LABEL,
        retired_themes=(
            RetiredTheme(theme="平局收割", tickets=23, ticket_hits=0,
                         legs=69, leg_hits=11),
        ),
    )
    out = render_bold_plan(plan)
    assert "主题汰留" in out
    assert "平局收割" in out
    assert "0/23 张" in out
    assert "69 腿" in out
    assert "30 门槛" in out
    assert "Phase A" in out
    body = out[len(HARD_LABEL):]
    for word in _BANNED_WORDS:
        assert word not in body, f"advantage word leaked: {word}"


def test_render_skips_retirement_notice_when_no_themes_retired() -> None:
    """spec §24 — empty ``retired_themes`` → no line rendered (no
    clean-day pollution)."""
    plan = BoldComboPlan(
        run_date="2026-05-25",
        day_chaos=8,
        chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=[],
        label=HARD_LABEL,
        retired_themes=(),
    )
    assert "主题汰留" not in render_bold_plan(plan)


def test_render_retirement_notice_emits_one_line_per_retired_theme() -> None:
    """spec §24 — multiple retired themes → one line each, in input order."""
    from nutmeg.services.jczq_bold_combos import RetiredTheme

    plan = BoldComboPlan(
        run_date="2026-05-25",
        day_chaos=8,
        chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=[],
        label=HARD_LABEL,
        retired_themes=(
            RetiredTheme(theme="平局收割", tickets=23, ticket_hits=0,
                         legs=69, leg_hits=11),
            RetiredTheme(theme="冷门比分梦", tickets=12, ticket_hits=0,
                         legs=36, leg_hits=2),
        ),
    )
    notice_lines = [
        ln for ln in render_bold_plan(plan).splitlines()
        if "主题汰留" in ln
    ]
    assert len(notice_lines) == 2
    assert "平局收割" in notice_lines[0]
    assert "冷门比分梦" in notice_lines[1]


def test_render_skips_degenerate_pool_notice_when_pool_is_rich() -> None:
    """Non-degenerate pool → no notice rendered."""
    legs_by_id = {
        "M1_a": _typed_leg(match_no="M1", market="crs", pick_label="1:1"),
        "M1_b": _typed_leg(match_no="M1", market="had", pick_label="平"),
        "M2": _typed_leg(match_no="M2", market="hhad", pick_label="让平"),
        "M3": _typed_leg(match_no="M3", market="crs", pick_label="0:0"),
    }
    tickets = [
        _typed_ticket([legs_by_id["M1_a"], legs_by_id["M2"], legs_by_id["M3"]]),
        _typed_ticket([legs_by_id["M1_b"], legs_by_id["M2"], legs_by_id["M3"]]),
    ]
    plan = BoldComboPlan(
        run_date="2026-05-20",
        day_chaos=8,
        chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=tickets,
        label=HARD_LABEL,
    )
    out = render_bold_plan(plan)
    assert "腿池退化" not in out


# ---------------------------------------------------------------------------
# Task 6 — engine assembly + welded honest label (spec §7 acceptance)
# ---------------------------------------------------------------------------

# Spec §7: every output must contain NONE of these advantage words.
_BANNED_WORDS = ("胜率", "edge", "+EV", "正期望", "推荐下注", "重仓")


def _engine_day() -> list[BoldMatch]:
    """A spread of synthetic 体彩 matches — some calm, some wild — for engine
    integration tests. Distinct match numbers (Rule O)."""
    return [
        _wild_match("周日001"),
        _wild_match("周日002"),
        _calm_match("周日003"),
        _match(
            match_no="周日004",
            tc_odds={"home": 1.35, "draw": 4.5, "away": 8.0},
            euro_odds={"home": 1.30, "draw": 5.0, "away": 9.0},
            euro_opening={"home": 1.40, "draw": 4.6, "away": 8.0},
            per_book_odds={
                "home": [1.25, 1.30, 1.40],
                "draw": [4.5, 5.0, 5.5],
                "away": [8.0, 9.0, 10.0],
            },
            tags={"强胆场"},
        ),
        _match(
            match_no="周日005",
            tc_odds={"home": 2.6, "draw": 3.1, "away": 2.7},
            euro_odds={"home": 2.2, "draw": 3.3, "away": 3.2},
            euro_opening={"home": 2.5, "draw": 3.2, "away": 2.9},
            per_book_odds={
                "home": [2.0, 2.2, 2.5],
                "draw": [3.1, 3.3, 3.5],
                "away": [2.9, 3.2, 3.6],
            },
            tags={"coinflip", "hi-vol"},
        ),
        _match(
            match_no="周日006",
            tc_odds={"home": 4.0, "draw": 3.4, "away": 1.85},
            euro_odds={"home": 5.0, "draw": 3.6, "away": 1.7},
            euro_opening={"home": 4.2, "draw": 3.5, "away": 1.9},
            per_book_odds={
                "home": [4.0, 5.0, 6.0],
                "draw": [3.4, 3.6, 3.8],
                "away": [1.6, 1.7, 1.8],
            },
            tags={"舒服盘"},
        ),
    ]


def test_hard_label_is_the_exact_welded_text() -> None:
    assert HARD_LABEL == (
        "🎲 娱乐性质 · 非 edge · 长期约 −13% 抽水期望 · 仅用娱乐预算下注"
    )


def test_engine_generate_returns_a_bold_combo_plan() -> None:
    plan = BoldComboEngine().generate("2026-05-18", _engine_day())

    assert isinstance(plan, BoldComboPlan)
    assert plan.run_date == "2026-05-18"
    assert plan.label == HARD_LABEL
    assert 0 <= plan.day_chaos <= 100
    assert plan.chaos_band in ("平静", "中等", "混乱")
    assert plan.anchor.kind == "稳健底仓"
    assert "高命中" in plan.anchor.note
    assert plan.tickets
    for ticket in plan.tickets:
        assert ticket.fold in (3, 4, 5)


def test_engine_generate_empty_day_does_not_crash() -> None:
    plan = BoldComboEngine().generate("2026-05-18", [])
    assert plan.label == HARD_LABEL
    assert plan.tickets == []


def test_render_bold_plan_welds_label_at_the_top() -> None:
    plan = BoldComboEngine().generate("2026-05-18", _engine_day())

    rendered = render_bold_plan(plan)

    assert rendered.startswith(HARD_LABEL)
    # The day chaos line appears near the top.
    head = "\n".join(rendered.splitlines()[:4])
    assert "大盘面混乱值" in head


def test_render_bold_plan_contains_no_advantage_wording() -> None:
    plan = BoldComboEngine().generate("2026-05-18", _engine_day())

    rendered = render_bold_plan(plan)

    for word in _BANNED_WORDS:
        # The 🎲 label itself legitimately contains the negation "非 edge";
        # strip the label line before scanning the body for banned words.
        body = rendered[len(HARD_LABEL):]
        assert word not in body, f"advantage word leaked into output: {word}"
    # The boldness number is labelled 大胆分 — never 胜率/信心.
    assert "大胆分" in rendered


def test_render_bold_plan_shows_no_probability_or_ev_columns() -> None:
    plan = BoldComboEngine().generate("2026-05-18", _engine_day())
    rendered = render_bold_plan(plan)
    assert "信心" not in rendered
    assert "EV" not in rendered


# ---------------------------------------------------------------------------
# Task 7 — context.json → BoldMatch loader
# ---------------------------------------------------------------------------


def test_bold_matches_from_context_reads_tc_odds_and_tags() -> None:
    from nutmeg.services.jczq_bold_combos import bold_matches_from_context

    context = {
        "matches": [
            {
                "match_no": "周日001",
                "league": "日职",
                "home_team": "主队",
                "away_team": "客队",
                "role": "强胆场",
                "candidates": [
                    {"pool": "had", "pick": "胜", "odds": 1.8},
                    {"pool": "had", "pick": "平", "odds": 3.4},
                    {"pool": "had", "pick": "负", "odds": 4.2},
                    {"pool": "hhad", "pick": "让胜", "odds": 6.6},
                ],
            }
        ]
    }

    matches = bold_matches_from_context(context, euro_by_match_no={})

    assert len(matches) == 1
    match = matches[0]
    assert match.match_no == "周日001"
    assert match.tc_odds == {"home": 1.8, "draw": 3.4, "away": 4.2}
    assert "强胆场" in match.tags  # role mapped to a heat tag
    # No 欧赔 supplied → euro fields empty → graceful degradation downstream.
    assert match.euro_odds == {}
    assert match.per_book_odds == {}


def test_bold_matches_from_context_skips_matches_without_had_pool() -> None:
    from nutmeg.services.jczq_bold_combos import bold_matches_from_context

    context = {
        "matches": [
            {
                "match_no": "周日002",
                "league": "日职",
                "home_team": "主",
                "away_team": "客",
                "candidates": [{"pool": "hhad", "pick": "让胜", "odds": 2.0}],
            }
        ]
    }

    assert bold_matches_from_context(context, euro_by_match_no={}) == []


def test_bold_matches_from_context_merges_euro_odds() -> None:
    from nutmeg.services.jczq_bold_combos import bold_matches_from_context

    context = {
        "matches": [
            {
                "match_no": "周日003",
                "league": "英超",
                "home_team": "主",
                "away_team": "客",
                "candidates": [
                    {"pool": "had", "pick": "胜", "odds": 2.0},
                    {"pool": "had", "pick": "平", "odds": 3.3},
                    {"pool": "had", "pick": "负", "odds": 3.5},
                ],
            }
        ]
    }
    euro = {
        "周日003": {
            "odds": {"home": 1.9, "draw": 3.4, "away": 3.8},
            "opening": {"home": 2.1, "draw": 3.3, "away": 3.5},
            "per_book": {
                "home": [1.8, 1.9, 2.0],
                "draw": [3.3, 3.4, 3.5],
                "away": [3.6, 3.8, 4.0],
            },
        }
    }

    matches = bold_matches_from_context(context, euro_by_match_no=euro)

    assert matches[0].euro_odds == {"home": 1.9, "draw": 3.4, "away": 3.8}
    assert matches[0].euro_opening == {"home": 2.1, "draw": 3.3, "away": 3.5}
    assert matches[0].per_book_odds["home"] == [1.8, 1.9, 2.0]


# ---------------------------------------------------------------------------
# Acceptance — the engine imports NO predictive model (spec §7)
# ---------------------------------------------------------------------------


def test_engine_module_imports_no_predictive_model() -> None:
    """The bold-combo engine consumes only 体彩 odds + 欧赔 — it must NOT
    import the retired predictive model (``dixon_coles`` / ``ValueBoardService``
    / anything under ``nutmeg.models``). Asserted by parsing every import
    statement in the module's AST (spec §7)."""
    source = (
        Path(__file__).parents[1]
        / "nutmeg"
        / "services"
        / "jczq_bold_combos.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.append(module)
            imported.extend(f"{module}.{a.name}" for a in node.names)

    banned = ("dixon_coles", "ValueBoardService", "nutmeg.models")
    for token in banned:
        leaks = [name for name in imported if token in name]
        assert not leaks, f"engine imports a predictive model: {leaks}"


# ---------------------------------------------------------------------------
# Multi-market extension — Task 5: market vocabulary + dataclass fields
# ---------------------------------------------------------------------------


def test_market_vocabulary_constants() -> None:
    from nutmeg.services.jczq_bold_combos import (
        MARKET_LABELS,
        MARKET_SIGNALS,
        MARKETS,
    )

    assert MARKETS == ("had", "hhad", "ttg", "crs")
    # had has all five signals; hhad/crs three; ttg four (大小球 dispersion).
    assert set(MARKET_SIGNALS["had"]) == {
        "conflict", "contrarian", "drift", "dispersion", "heat",
    }
    assert set(MARKET_SIGNALS["hhad"]) == {"conflict", "contrarian", "heat"}
    assert set(MARKET_SIGNALS["ttg"]) == {
        "conflict", "contrarian", "dispersion", "heat",
    }
    assert set(MARKET_SIGNALS["crs"]) == {"conflict", "contrarian", "heat"}
    assert MARKET_LABELS == {
        "had": "胜平负", "hhad": "让球", "ttg": "总进球", "crs": "比分",
    }


def test_bold_match_multi_market_fields_default_empty() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch

    # A v1-style had-only BoldMatch — multi-market fields default empty.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
    )
    assert match.hhad_odds == {}
    assert match.ttg_odds == {}
    assert match.crs_odds == {}
    assert match.ou_odds == {}
    assert match.hhad_line == 0.0


def test_bold_leg_carries_market_and_label() -> None:
    from nutmeg.services.jczq_bold_combos import BoldLeg

    leg = BoldLeg(
        match_no="周一001", league="芬超", home="A", away="B",
        market="crs", pick="2:1", pick_label="2:1",
        tc_odds=7.5, boldness=0.4, reason="x",
    )
    assert leg.market == "crs"
    assert leg.pick_label == "2:1"


# ---------------------------------------------------------------------------
# Multi-market extension — Task 6: internal + external conflict signals
# ---------------------------------------------------------------------------


def test_internal_conflict_had_flags_crs_vs_had_disagreement() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, internal_conflict

    # 体彩 had board: home favorite (~0.5). 体彩 crs board: equal exact mass on
    # 1:0 / 0:0 / 0:1 → aggregates to home 1/3. The board contradicts itself.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 1.9, "draw": 3.4, "away": 4.5},
        crs_odds={"s01s00": 3.0, "s00s00": 3.0, "s00s01": 3.0},
    )
    conflict = internal_conflict(match, "had")
    assert conflict["home"] > 0.05          # direct ~0.5 vs derived ~0.33
    assert set(conflict) == {"home", "draw", "away"}


def test_internal_conflict_is_zero_without_crs() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, internal_conflict

    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
    )
    assert internal_conflict(match, "had") == {"home": 0.0, "draw": 0.0, "away": 0.0}


def test_external_conflict_ttg_compares_体彩_vs_国际大小球() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, external_conflict_ttg

    # 体彩 ttg leans under (total_1 cheap); 国际大小球 leans over → a real gap.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        ttg_odds={f"total_{k}": v for k, v in {
            0: 9.0, 1: 2.0, 2: 3.0, 3: 6.0, 4: 12.0, 5: 25.0, 6: 50.0, 7: 90.0,
        }.items()},
        ou_odds={"over": 1.6, "under": 2.4}, ou_line=2.5,
    )
    assert external_conflict_ttg(match) > 0.05


def test_external_conflict_ttg_zero_without_overunder() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, external_conflict_ttg

    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        ttg_odds={f"total_{k}": 5.0 for k in range(8)},
    )
    assert external_conflict_ttg(match) == 0.0


# ---------------------------------------------------------------------------
# Multi-market extension — Task 7: per-market boldness + bold leg
# ---------------------------------------------------------------------------


def test_market_boldness_weights_normalize_per_market() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, market_boldness

    # hhad has 3 active signals; with the heat term maxed and others 0 the
    # normalized heat weight is 1/3, so a heat of 1.0 → boldness 1/3.
    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        hhad_odds={"home": 2.5, "draw": 3.3, "away": 2.6}, hhad_line=-1.0,
        tags={"强胆场", "舒服盘", "coinflip", "draw_friendly"}, vig=0.20,
    )
    scores = market_boldness(match, "hhad")
    # heat clips to 1.0 (4 tags × 0.25); normalized hhad weight for heat = 1/3.
    assert all(abs(v - 1 / 3) < 0.34 for v in scores.values())
    assert set(scores) == {"home", "draw", "away"}


def test_bold_leg_for_market_populates_leg_fields() -> None:
    """bold_leg_for_market returns a leg with the right market, display label,
    and 体彩 odds consistent with the chosen outcome."""
    from nutmeg.services.jczq_bold_combos import BoldMatch, bold_leg_for_market

    # all crs outcomes are inside the realistic odds range (spec §13).
    match = BoldMatch(
        match_no="周一001", league="芬超", home="拉赫蒂", away="瓦萨",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s02s01": 7.5},
    )
    leg = bold_leg_for_market(match, "crs")
    assert leg is not None
    assert leg.market == "crs"
    assert leg.pick_label in {"1:0", "0:0", "2:1"}
    assert leg.tc_odds == match.crs_odds[leg.pick]   # odds match the picked key


def test_bold_leg_for_market_returns_none_without_market_odds() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, bold_leg_for_market

    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
    )
    assert bold_leg_for_market(match, "crs") is None    # no crs odds
    assert bold_leg_for_market(match, "had") is not None


# ---------------------------------------------------------------------------
# Multi-market extension — Task 8: cross-market pool + Rule-O combos
# ---------------------------------------------------------------------------


def test_candidate_legs_spans_markets() -> None:
    from nutmeg.services.jczq_bold_combos import BoldMatch, candidate_legs

    match = BoldMatch(
        match_no="周一001", league="芬超", home="A", away="B",
        tc_odds={"home": 2.0, "draw": 3.2, "away": 3.5},
        hhad_odds={"home": 2.5, "draw": 3.3, "away": 2.6}, hhad_line=-1.0,
        ttg_odds={f"total_{k}": 4.0 for k in range(8)},
        crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s03s02": 41.0},
    )
    legs = candidate_legs([match])
    # one match, four markets → up to MAX_LEGS_PER_MATCH legs kept.
    assert {lg.market for lg in legs} <= {"had", "hhad", "ttg", "crs"}
    assert len(legs) <= 2                       # MAX_LEGS_PER_MATCH cap
    assert all(lg.match_no == "周一001" for lg in legs)


def test_bold_combos_enforces_one_leg_per_match() -> None:
    from nutmeg.services.jczq_bold_combos import BoldLeg, bold_combos

    # Two legs share 周一001 (had + crs); a legal 3-fold cannot use both.
    legs = [
        BoldLeg("周一001", "L", "A", "B", "home", 3.0, 0.5, "x", market="had", pick_label="胜"),
        BoldLeg("周一001", "L", "A", "B", "s01s00", 7.0, 0.6, "x", market="crs", pick_label="1:0"),
        BoldLeg("周一002", "L", "C", "D", "away", 3.5, 0.5, "x", market="had", pick_label="负"),
        BoldLeg("周一003", "L", "E", "F", "draw", 3.2, 0.5, "x", market="had", pick_label="平"),
    ]
    tickets = bold_combos(legs, chaos=10)
    assert tickets
    for ticket in tickets:
        match_nos = [lg.match_no for lg in ticket.legs]
        assert len(match_nos) == len(set(match_nos))      # Rule O — distinct matches


# ---------------------------------------------------------------------------
# Multi-market extension — Task 9: Sporttery loader + snapshot + engine
# ---------------------------------------------------------------------------


def _sporttery_value() -> dict:
    """A minimal Sporttery getMatchCalculatorV1 'value' dict — 2 matches."""
    def match(no: str, home: str) -> dict:
        return {
            "matchNumStr": no, "businessDate": "2026-05-18",
            "matchStatus": "Selling", "leagueAbbName": "芬超",
            "homeTeamAbbName": home, "awayTeamAbbName": "客",
            "had": {"h": "2.00", "d": "3.20", "a": "3.50"},
            "hhad": {"h": "3.10", "d": "3.30", "a": "2.10", "goalLine": "-1"},
            "ttg": {f"s{k}": str(4.0 + k) for k in range(8)},
            "crs": {"s01s00": "6.50", "s01s00f": "0", "s00s00": "9.00",
                    "s02s01": "7.50", "s1sh": "80.0"},
        }
    return {"matchInfoList": [
        {"businessDate": "2026-05-18",
         "subMatchList": [match("周一001", "拉赫蒂"), match("周一002", "佐加顿斯")]}
    ]}


def test_bold_matches_from_sporttery_loads_all_markets() -> None:
    from nutmeg.services.jczq_bold_combos import bold_matches_from_sporttery

    matches = bold_matches_from_sporttery(
        _sporttery_value(), run_date="2026-05-18", bold_odds={}
    )
    assert len(matches) == 2
    m = matches[0]
    assert m.tc_odds == {"home": 2.0, "draw": 3.2, "away": 3.5}
    assert m.hhad_odds == {"home": 3.1, "draw": 3.3, "away": 2.1}
    assert m.hhad_line == -1.0
    assert m.ttg_odds["total_0"] == 4.0 and m.ttg_odds["total_7"] == 11.0
    # crs: the ...f flag key is excluded; exact + 其他 keys kept.
    assert "s01s00f" not in m.crs_odds
    assert m.crs_odds["s02s01"] == 7.5 and m.crs_odds["s1sh"] == 80.0


def test_snapshot_round_trip(tmp_path) -> None:
    from nutmeg.services.jczq_bold_combos import (
        load_sporttery_snapshot,
        persist_sporttery_snapshot,
    )

    persist_sporttery_snapshot("2026-05-18", tmp_path, _sporttery_value())
    loaded = load_sporttery_snapshot("2026-05-18", tmp_path)
    assert loaded is not None
    assert loaded["matchInfoList"][0]["subMatchList"][0]["matchNumStr"] == "周一001"
    assert load_sporttery_snapshot("2025-01-01", tmp_path) is None   # absent → None


def test_engine_generate_produces_cross_market_legs() -> None:
    from nutmeg.services.jczq_bold_combos import (
        BoldComboEngine,
        bold_matches_from_sporttery,
    )

    matches = bold_matches_from_sporttery(
        _sporttery_value(), run_date="2026-05-18", bold_odds={}
    )
    # widen to 3 matches so a 3-fold is possible
    matches = matches + [matches[0].__class__(
        match_no="周一003", league="芬超", home="X", away="Y",
        tc_odds={"home": 2.1, "draw": 3.1, "away": 3.4},
        crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s03s02": 41.0},
    )]
    plan = BoldComboEngine().generate("2026-05-18", matches)
    rendered_markets = {
        lg.market for t in plan.tickets for lg in t.legs
    }
    assert rendered_markets                       # at least one market present
    assert plan.label.startswith("🎲")


# ---------------------------------------------------------------------------
# spec §10 — payout cap awareness + per-ticket market mix
# ---------------------------------------------------------------------------


def _combo_leg(match_no: str, market: str, odds: float, boldness: float = 0.4):
    """A bare BoldLeg for combination-generation tests."""
    from nutmeg.services.jczq_bold_combos import BoldLeg

    return BoldLeg(
        match_no=match_no, league="L", home="H", away="A",
        pick="x", tc_odds=odds, boldness=boldness, reason="r",
        market=market, pick_label="x",
    )


def test_effective_odds_caps_at_jczq_payout_limit() -> None:
    from nutmeg.services.jczq_bold_combos import (
        JCZQ_PAYOUT_CAP_YUAN,
        REFERENCE_STAKE_YUAN,
        _effective_odds,
    )

    cap = JCZQ_PAYOUT_CAP_YUAN / REFERENCE_STAKE_YUAN
    assert _effective_odds(1000.0) == 1000.0          # under cap — unchanged
    assert _effective_odds(cap * 9) == cap            # over cap — capped


def test_bold_combos_caps_legs_per_market_when_pool_is_multimarket() -> None:
    from collections import Counter

    from nutmeg.services.jczq_bold_combos import (
        MAX_LEGS_PER_MARKET_PER_TICKET,
        bold_combos,
    )

    # pool spans had + crs → the per-market cap is enforced; no ticket may be
    # three had legs.
    legs = [
        _combo_leg("周一001", "had", 3.0), _combo_leg("周一002", "had", 3.2),
        _combo_leg("周一003", "had", 3.4), _combo_leg("周一004", "crs", 8.0),
        _combo_leg("周一005", "crs", 9.0),
    ]
    tickets = bold_combos(legs, chaos=10)
    assert tickets
    for ticket in tickets:
        counts = Counter(lg.market for lg in ticket.legs)
        assert max(counts.values()) <= MAX_LEGS_PER_MARKET_PER_TICKET


def test_bold_combos_skips_market_cap_for_single_market_pool() -> None:
    from nutmeg.services.jczq_bold_combos import bold_combos

    # had-only pool (v1 behavior) → the cap must NOT fire, or no ticket exists.
    legs = [
        _combo_leg("周一001", "had", 3.0), _combo_leg("周一002", "had", 3.2),
        _combo_leg("周一003", "had", 3.4),
    ]
    tickets = bold_combos(legs, chaos=10)
    assert tickets                                    # 3-had ticket still produced
    assert tickets[0].fold == 3


def test_bold_combos_flags_over_cap_ticket_honestly() -> None:
    from nutmeg.services.jczq_bold_combos import bold_combos

    # three had legs at 200× each → 8,000,000× combined → over the 250万× cap.
    legs = [
        _combo_leg("周一001", "had", 200.0), _combo_leg("周一002", "had", 200.0),
        _combo_leg("周一003", "had", 200.0),
    ]
    tickets = bold_combos(legs, chaos=10)
    assert tickets
    assert "封顶" in tickets[0].note                   # honest cap annotation
    assert tickets[0].total_odds == 8_000_000.0       # real product NOT truncated


# ---------------------------------------------------------------------------
# spec §11 — no-胜平负 matches load; cross-ticket concentration
# ---------------------------------------------------------------------------


def test_bold_matches_from_sporttery_keeps_match_without_胜平负() -> None:
    """A 让球/总进球/比分 board with no 胜平负 (体彩 hasn't opened had yet) must
    still load — the multi-market engine scores those markets without 胜平负
    (spec §11.1)."""
    from nutmeg.services.jczq_bold_combos import bold_matches_from_sporttery

    value = {"matchInfoList": [{"businessDate": "2026-05-18", "subMatchList": [{
        "matchNumStr": "周一004", "businessDate": "2026-05-18",
        "matchStatus": "Selling", "leagueAbbName": "英超",
        "homeTeamAbbName": "阿森纳", "awayTeamAbbName": "伯恩利",
        "had": {},                                          # 胜平负 not opened
        "hhad": {"h": "2.62", "d": "4.30", "a": "1.94", "goalLine": "-2"},
        "ttg": {f"s{k}": str(5.0 + k) for k in range(8)},
        "crs": {"s02s00": "5.75", "s03s00": "4.90", "s1sh": "5.75"},
    }]}]}

    matches = bold_matches_from_sporttery(value, run_date="2026-05-18", bold_odds={})

    assert len(matches) == 1
    m = matches[0]
    assert m.match_no == "周一004"
    assert m.tc_odds == {}                                  # no 胜平负 leg possible
    assert m.hhad_odds == {"home": 2.62, "draw": 4.30, "away": 1.94}
    assert m.ttg_odds and m.crs_odds                        # other markets loaded


def test_bold_matches_from_sporttery_skips_match_with_no_markets() -> None:
    """A match with every pool empty is still skipped (spec §11.1)."""
    from nutmeg.services.jczq_bold_combos import bold_matches_from_sporttery

    value = {"matchInfoList": [{"businessDate": "2026-05-18", "subMatchList": [{
        "matchNumStr": "周一009", "businessDate": "2026-05-18",
        "matchStatus": "Selling", "leagueAbbName": "x",
        "homeTeamAbbName": "A", "awayTeamAbbName": "B",
        "had": {}, "hhad": {}, "ttg": {}, "crs": {},
    }]}]}

    assert bold_matches_from_sporttery(
        value, run_date="2026-05-18", bold_odds={}
    ) == []


def test_bold_combos_diversifies_tickets_across_matches() -> None:
    """Diversity-penalized selection spreads tickets across matches (spec §11.2)
    — with 6 equal-score legs the 3-fold tickets together cover every match,
    instead of reusing the same lead matches."""
    from nutmeg.services.jczq_bold_combos import bold_combos

    legs = [_combo_leg(f"周一{i:03d}", "had", 3.0, boldness=0.5) for i in range(1, 7)]
    tickets = bold_combos(legs, chaos=10)             # chaos<34 → 3 three-folds
    three_folds = [t for t in tickets if t.fold == 3]
    assert len(three_folds) >= 2
    covered = {lg.match_no for t in three_folds for lg in t.legs}
    assert len(covered) == 6                          # spread across all matches


def test_render_bold_plan_warns_on_cross_ticket_concentration() -> None:
    """A match in most bold tickets triggers the honest 🟦 concentration note."""
    from nutmeg.services.jczq_bold_combos import (
        BoldComboPlan,
        BoldTicket,
        anchor_ticket,
        render_bold_plan,
    )

    def ticket(idx: int, partner: str) -> BoldTicket:
        return BoldTicket(
            id=f"大胆票{idx}", kind="大胆票",
            legs=[
                _combo_leg("周一001", "had", 3.0),
                _combo_leg(partner, "had", 3.0),
                _combo_leg(f"周一9{idx:02d}", "had", 3.0),
            ],
            fold=3, total_odds=27.0, avg_boldness=0.4, note="n",
        )

    plan = BoldComboPlan(
        run_date="2026-05-18", day_chaos=10, chaos_band="平静",
        anchor=anchor_ticket([]),
        tickets=[ticket(1, "周一002"), ticket(2, "周一003"), ticket(3, "周一004")],
    )
    out = render_bold_plan(plan)
    assert "集中度提示" in out
    assert "周一001" in out                            # the over-shared match named


def test_render_bold_plan_notes_idle_budget_is_a_choice() -> None:
    """The footer honestly says multiple tickets ≠ diversification (spec §11.2)."""
    from nutmeg.services.jczq_bold_combos import BoldComboEngine, render_bold_plan

    plan = BoldComboEngine().generate("2026-05-18", [])
    out = render_bold_plan(plan)
    assert "一张都不买" in out


# ---------------------------------------------------------------------------
# spec §12 — market-balanced candidate pool (defeats 比分 dominance)
# ---------------------------------------------------------------------------


def test_engine_tickets_mix_markets_despite_比分_dominance() -> None:
    """比分 legs dominate boldness, but the market-balanced pool keeps ≥2
    markets so every bold ticket mixes markets — no all-比分 ticket (spec §12)."""
    from nutmeg.services.jczq_bold_combos import BoldComboEngine, BoldMatch

    # four matches, each with 胜平负 + 比分 odds; the cold 比分 scorelines win
    # boldness, so a plain pool would be all 比分.
    matches = [
        BoldMatch(
            match_no=f"周一{i:03d}", league="L", home="H", away="A",
            tc_odds={"home": 2.0, "draw": 3.3, "away": 3.6},
            crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s03s02": 41.0, "s02s05": 200.0},
        )
        for i in range(1, 5)
    ]
    plan = BoldComboEngine().generate("2026-05-18", matches)

    assert plan.tickets
    for ticket in plan.tickets:
        markets = {lg.market for lg in ticket.legs}
        assert len(markets) >= 2, f"all-one-market ticket: {sorted(markets)}"


def test_balanced_pool_caps_one_market_below_pool_size() -> None:
    """No single market may fill the whole pool when ≥2 markets exist (spec §12)."""
    from nutmeg.services.jczq_bold_combos import BoldMatch, _balanced_pool

    matches = [
        BoldMatch(
            match_no=f"周一{i:03d}", league="L", home="H", away="A",
            tc_odds={"home": 2.0, "draw": 3.3, "away": 3.6},
            crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s03s02": 41.0},
        )
        for i in range(1, 5)
    ]
    pool = _balanced_pool(matches, pool_n=4)

    assert len(pool) == 4
    assert len({lg.market for lg in pool}) >= 2        # not a single-market pool


# ---------------------------------------------------------------------------
# spec §13 — realistic target odds band
# ---------------------------------------------------------------------------


def test_band_fit_peaks_inside_target_band() -> None:
    """_band_fit is 1.0 inside the realistic band, decays outside (spec §13)."""
    from nutmeg.services.jczq_bold_combos import _band_fit

    assert _band_fit(200.0, 3) == 1.0                  # inside 80-400×
    assert _band_fit(40.0, 3) < 1.0                    # below the band
    assert _band_fit(8000.0, 3) < 0.1                  # moonshot — crushed
    # the band scales up with fold — 3000× fits a 5-fold but not a 3-fold.
    assert _band_fit(3000.0, 5) > _band_fit(3000.0, 3)


def test_bold_leg_for_market_prefers_realistic_odds_range() -> None:
    """bold_leg_for_market picks a leg inside the realistic odds range, not the
    coldest freak scoreline (spec §13)."""
    from nutmeg.services.jczq_bold_combos import (
        LEG_ODDS_MAX,
        LEG_ODDS_MIN,
        BoldMatch,
        bold_leg_for_market,
    )

    match = BoldMatch(
        match_no="周一001", league="L", home="H", away="A",
        tc_odds={"home": 2.0, "draw": 3.3, "away": 3.6},
        crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s00s05": 800.0},
    )
    leg = bold_leg_for_market(match, "crs")

    assert leg is not None
    assert LEG_ODDS_MIN <= leg.tc_odds <= LEG_ODDS_MAX  # not the 800× freak


def test_engine_bold_tickets_land_in_realistic_odds_band() -> None:
    """Bold 3-fold tickets target ~80-400× — realistic, not million-fold
    moonshots (spec §13)."""
    from nutmeg.services.jczq_bold_combos import BoldComboEngine, BoldMatch

    matches = [
        BoldMatch(
            match_no=f"周一{i:03d}", league="L", home="H", away="A",
            tc_odds={"home": 2.0, "draw": 3.5, "away": 4.0},
            ttg_odds={
                "total_0": 30.0, "total_1": 5.0, "total_2": 3.3,
                "total_3": 4.0, "total_4": 6.5, "total_5": 12.0,
                "total_6": 25.0, "total_7": 40.0,
            },
            crs_odds={
                "s01s00": 6.0, "s00s00": 9.0, "s02s01": 7.5,
                "s03s02": 41.0, "s00s05": 800.0,
            },
        )
        for i in range(1, 5)
    ]
    plan = BoldComboEngine().generate("2026-05-18", matches)

    assert plan.tickets
    three_folds = [t for t in plan.tickets if t.fold == 3]
    assert three_folds
    for ticket in three_folds:
        assert ticket.total_odds < 2000, f"moonshot 3-fold: {ticket.total_odds}"


# ---------------------------------------------------------------------------
# spec §14 — 欧赔 snapshot makes --replay reproducible
# ---------------------------------------------------------------------------


def test_bold_odds_snapshot_round_trip(tmp_path) -> None:
    """A collect_bold_odds result survives persist → load unchanged (spec §14)."""
    from nutmeg.data.fcom500 import MarketOdds
    from nutmeg.services.jczq_bold_combos import (
        load_bold_odds_snapshot,
        persist_bold_odds_snapshot,
    )

    bold_odds = {
        "周一001": {
            "match_winner": MarketOdds(
                odds={"home": 2.1, "draw": 3.3, "away": 3.5},
                fair_probability={"home": 0.45, "draw": 0.30, "away": 0.25},
                independent=True,
                bookmaker_count=29,
                opening_odds={"home": 2.0, "draw": 3.4, "away": 3.6},
                per_book_odds={"home": [2.1, 2.05], "draw": [3.3], "away": [3.5]},
            ),
            "over_under": MarketOdds(
                odds={"over": 1.9, "under": 1.95}, fair_probability={},
                independent=True, line="2.5",
            ),
        }
    }
    persist_bold_odds_snapshot("2026-05-18", tmp_path, bold_odds)
    loaded = load_bold_odds_snapshot("2026-05-18", tmp_path)
    assert loaded == bold_odds                       # round-trips exactly


def test_load_bold_odds_snapshot_absent_returns_empty(tmp_path) -> None:
    """A date with no 国际-odds snapshot degrades to 体彩-only, never crashes
    (spec §14)."""
    from nutmeg.services.jczq_bold_combos import load_bold_odds_snapshot

    assert load_bold_odds_snapshot("2025-01-01", tmp_path) == {}


def test_replay_snapshot_feeds_欧赔_into_matches(tmp_path) -> None:
    """The §14 fix: a snapshotted 国际 欧赔 reaches BoldMatch.euro_odds on
    replay — replay is no longer silently 体彩-only (chaos=0)."""
    from nutmeg.data.fcom500 import MarketOdds
    from nutmeg.services.jczq_bold_combos import (
        bold_matches_from_sporttery,
        load_bold_odds_snapshot,
        persist_bold_odds_snapshot,
    )

    bold_odds = {
        "周一001": {"match_winner": MarketOdds(
            odds={"home": 5.0, "draw": 4.0, "away": 1.6},
            fair_probability={}, independent=True,
        )},
    }
    persist_bold_odds_snapshot("2026-05-18", tmp_path, bold_odds)
    loaded = load_bold_odds_snapshot("2026-05-18", tmp_path)

    matches = bold_matches_from_sporttery(
        _sporttery_value(), run_date="2026-05-18", bold_odds=loaded
    )
    m001 = next(m for m in matches if m.match_no == "周一001")
    assert m001.euro_odds == {"home": 5.0, "draw": 4.0, "away": 1.6}
    # a match absent from the snapshot still degrades gracefully to 体彩-only.
    m002 = next(m for m in matches if m.match_no == "周一002")
    assert m002.euro_odds == {}


# ---------------------------------------------------------------------------
# spec §15 — themed 剧本 tickets
# ---------------------------------------------------------------------------


def _themed_leg(match_no: str, market: str, pick: str, odds: float = 5.0):
    """A BoldLeg with an explicit pick — for theme-classification tests."""
    from nutmeg.services.jczq_bold_combos import BoldLeg

    return BoldLeg(
        match_no=match_no, league="L", home="H", away="A",
        pick=pick, tc_odds=odds, boldness=0.4, reason="r",
        market=market, pick_label=pick,
    )


def test_ticket_theme_draw_majority() -> None:
    """A ticket whose majority legs back a draw outcome → 平局收割 (spec §15)."""
    from nutmeg.services.jczq_bold_combos import ticket_theme

    legs = [
        _themed_leg("周一001", "had", "draw"),
        _themed_leg("周一002", "hhad", "draw"),
        _themed_leg("周一003", "crs", "s02s00"),       # 2:0 — not a draw
    ]
    theme, script = ticket_theme(legs)
    assert theme == "平局收割"
    assert script                                      # carries a 剧本 line


def test_ticket_theme_market_majorities() -> None:
    """A single market holding the majority → that market's theme (spec §15)."""
    from nutmeg.services.jczq_bold_combos import ticket_theme

    score = [
        _themed_leg("周一001", "crs", "s02s01"),
        _themed_leg("周一002", "crs", "s03s00"),
        _themed_leg("周一003", "ttg", "total_4"),
    ]
    assert ticket_theme(score)[0] == "冷门比分梦"

    handicap = [
        _themed_leg("周一001", "hhad", "home"),
        _themed_leg("周一002", "hhad", "away"),
        _themed_leg("周一003", "ttg", "total_3"),
    ]
    assert ticket_theme(handicap)[0] == "黑马让球"

    goals = [
        _themed_leg("周一001", "ttg", "total_4"),
        _themed_leg("周一002", "ttg", "total_1"),
        _themed_leg("周一003", "crs", "s02s01"),
    ]
    assert ticket_theme(goals)[0] == "进球狂欢"


def test_ticket_theme_no_majority_is_mixed() -> None:
    """One leg per market, no draw majority → 全市场混搭 (spec §15)."""
    from nutmeg.services.jczq_bold_combos import ticket_theme

    legs = [
        _themed_leg("周一001", "had", "home"),
        _themed_leg("周一002", "hhad", "away"),
        _themed_leg("周一003", "crs", "s02s01"),
    ]
    assert ticket_theme(legs)[0] == "全市场混搭"
    assert ticket_theme([]) == ("", "")                # empty → renderer omits it


def test_bold_tickets_carry_distinct_themes() -> None:
    """bold_combos picks one ticket per 剧本 theme — distinct characters, not
    the same legs permuted (spec §15)."""
    from nutmeg.services.jczq_bold_combos import bold_combos, ticket_theme

    # a 6-leg pool spanning markets: crs / hhad / ttg, all non-draw picks.
    legs = [
        _themed_leg("周一001", "crs", "s02s01", 6.0),
        _themed_leg("周一002", "crs", "s03s01", 7.0),
        _themed_leg("周一003", "hhad", "home", 5.0),
        _themed_leg("周一004", "hhad", "away", 4.5),
        _themed_leg("周一005", "ttg", "total_4", 5.5),
        _themed_leg("周一006", "ttg", "total_1", 5.0),
    ]
    tickets = bold_combos(legs, chaos=10)

    assert tickets
    themes = {ticket_theme(t.legs)[0] for t in tickets}
    assert len(themes) >= 2, f"all tickets share one theme: {themes}"


def test_render_bold_plan_shows_theme_and_剧本() -> None:
    """A rendered bold ticket carries its 剧本 theme in the header and a 剧本
    narrative line below the legs (spec §15). Banned-word coverage stays with
    test_render_bold_plan_contains_no_advantage_wording, which now also scans
    the 剧本 lines."""
    from nutmeg.services.jczq_bold_combos import (
        BoldComboEngine,
        BoldMatch,
        render_bold_plan,
    )

    matches = [
        BoldMatch(
            match_no=f"周一{i:03d}", league="L", home="H", away="A",
            tc_odds={"home": 2.0, "draw": 3.4, "away": 3.8},
            hhad_odds={"home": 3.0, "draw": 3.3, "away": 2.2}, hhad_line=-1.0,
            ttg_odds={
                f"total_{k}": v for k, v in enumerate(
                    [26.0, 5.0, 3.3, 3.6, 6.0, 12.0, 25.0, 40.0]
                )
            },
            crs_odds={"s01s00": 6.0, "s00s00": 9.0, "s02s01": 7.5, "s03s02": 41.0},
        )
        for i in range(1, 6)
    ]
    out = render_bold_plan(BoldComboEngine().generate("2026-05-18", matches))

    assert "剧本：" in out                              # narrative line present
    assert any(t in out for t in (
        "平局收割", "冷门比分梦", "黑马让球", "进球狂欢", "全市场混搭",
    ))


# ---------------------------------------------------------------------------
# spec §19 — 同场反向公示 — anchor leg vs same-match bold leg directional
# conflict (5/20 review)
# ---------------------------------------------------------------------------


def _anchor_leg(match_no: str, pick: str, pick_label: str, tc_odds: float) -> BoldLeg:
    """A had-only anchor leg (the only kind anchor_ticket emits)."""
    return BoldLeg(
        match_no=match_no, league="L", home="H", away="A",
        pick=pick, tc_odds=tc_odds, boldness=0.0,
        reason=f"{pick_label}向 · 体彩最强热门（最低赔）",
        market="had", pick_label=pick_label,
    )


def _anchor(legs: list[BoldLeg]) -> BoldTicket:
    return BoldTicket(
        id="稳健底仓", kind="稳健底仓", legs=legs,
        fold=len(legs), total_odds=3.0, avg_boldness=0.0, note="",
    )


def _plan(
    *, anchor: BoldTicket, tickets: list[BoldTicket],
    pool_signals: PoolSignals | None = None,
    day_chaos: int = 8,
) -> BoldComboPlan:
    return BoldComboPlan(
        run_date="2026-05-20",
        day_chaos=day_chaos,
        chaos_band="平静",
        anchor=anchor,
        tickets=tickets,
        label=HARD_LABEL,
        pool_signals=pool_signals if pool_signals is not None else PoolSignals(),
    )


def test_same_match_contradictions_5_20_case_anchor_home_vs_bold_draw() -> None:
    """spec §19 — anchor picks 003 胜 (home) while bold ticket holds 003
    比分 1:1 (draw direction). Engine is reading 003 in two opposing ways —
    surface a fact-only ⚠️ notice."""
    anchor = _anchor([_anchor_leg("周三003", "home", "胜", 1.34)])
    bold_leg_1_1 = BoldLeg(
        match_no="周三003", league="L", home="库奥皮奥", away="雅罗",
        pick="s01s01", tc_odds=9.0, boldness=0.39,
        reason="比分 · 1:1 · 大胆腿",
        market="crs", pick_label="1:1",
    )
    bold_ticket = BoldTicket(
        id="大胆票1", kind="大胆票",
        legs=[bold_leg_1_1], fold=1, total_odds=9.0,
        avg_boldness=0.39, note="",
    )
    plan = _plan(anchor=anchor, tickets=[bold_ticket])
    notices = same_match_contradictions(plan)
    assert len(notices) == 1
    notice = notices[0]
    assert "同场反向" in notice
    assert "周三003" in notice
    assert "[胜]" in notice and "1.34" in notice
    assert "比分 1:1" in notice and "9.00" in notice
    assert "方向相反" in notice


def test_same_match_contradictions_silent_when_directions_agree() -> None:
    """Anchor 胜 + bold crs 2:1 both vote home → no conflict."""
    anchor = _anchor([_anchor_leg("周三003", "home", "胜", 1.34)])
    bold = BoldLeg(
        match_no="周三003", league="L", home="H", away="A",
        pick="s02s01", tc_odds=7.0, boldness=0.3,
        reason="比分", market="crs", pick_label="2:1",
    )
    ticket = BoldTicket(
        id="大胆票1", kind="大胆票", legs=[bold],
        fold=1, total_odds=7.0, avg_boldness=0.3, note="",
    )
    plan = _plan(anchor=anchor, tickets=[ticket])
    assert same_match_contradictions(plan) == []


def test_same_match_contradictions_ignores_ttg_orthogonal_leg() -> None:
    """A bold ttg leg has no H/D/A direction → never a conflict (orthogonal)."""
    anchor = _anchor([_anchor_leg("周三003", "home", "胜", 1.34)])
    bold = BoldLeg(
        match_no="周三003", league="L", home="H", away="A",
        pick="total_4", tc_odds=5.0, boldness=0.3,
        reason="总进球", market="ttg", pick_label="4球",
    )
    ticket = BoldTicket(
        id="大胆票1", kind="大胆票", legs=[bold],
        fold=1, total_odds=5.0, avg_boldness=0.3, note="",
    )
    plan = _plan(anchor=anchor, tickets=[ticket])
    assert same_match_contradictions(plan) == []


def test_same_match_contradictions_dedups_repeated_bold_leg_across_tickets() -> None:
    """Same (match, market, pick_label) shared by multiple tickets → one notice."""
    anchor = _anchor([_anchor_leg("周三003", "home", "胜", 1.34)])
    bold = BoldLeg(
        match_no="周三003", league="L", home="H", away="A",
        pick="s01s01", tc_odds=9.0, boldness=0.39,
        reason="比分", market="crs", pick_label="1:1",
    )
    other = BoldLeg(
        match_no="M2", league="L", home="H", away="A",
        pick="draw", tc_odds=3.6, boldness=0.3,
        reason="让球", market="hhad", pick_label="让平",
    )
    tickets = [
        BoldTicket(id="大胆票1", kind="大胆票", legs=[bold, other],
                   fold=2, total_odds=32.4, avg_boldness=0.34, note=""),
        BoldTicket(id="大胆票2", kind="大胆票", legs=[bold],
                   fold=1, total_odds=9.0, avg_boldness=0.39, note=""),
    ]
    plan = _plan(anchor=anchor, tickets=tickets)
    notices = same_match_contradictions(plan)
    assert len(notices) == 1
    assert "周三003" in notices[0]


def test_same_match_contradictions_silent_when_anchor_empty() -> None:
    bold = BoldLeg(
        match_no="周三003", league="L", home="H", away="A",
        pick="s01s01", tc_odds=9.0, boldness=0.39,
        reason="比分", market="crs", pick_label="1:1",
    )
    ticket = BoldTicket(
        id="大胆票1", kind="大胆票", legs=[bold],
        fold=1, total_odds=9.0, avg_boldness=0.39, note="",
    )
    plan = _plan(anchor=_anchor([]), tickets=[ticket])
    assert same_match_contradictions(plan) == []


def test_render_includes_same_match_contradiction_notice() -> None:
    """Render injects §19 lines between §18 degenerate-notice (if any) and
    the empty separator before 稳健底仓; phrasing has no banned words."""
    anchor = _anchor([_anchor_leg("周三003", "home", "胜", 1.34)])
    bold = BoldLeg(
        match_no="周三003", league="L", home="库奥皮奥", away="雅罗",
        pick="s01s01", tc_odds=9.0, boldness=0.39,
        reason="比分", market="crs", pick_label="1:1",
    )
    ticket = BoldTicket(
        id="大胆票1", kind="大胆票", legs=[bold],
        fold=1, total_odds=9.0, avg_boldness=0.39, note="",
    )
    plan = _plan(anchor=anchor, tickets=[ticket])
    out = render_bold_plan(plan)
    assert "⚠️ 同场反向" in out
    assert "周三003" in out
    body = out[len(HARD_LABEL):]
    for word in _BANNED_WORDS:
        assert word not in body, f"advantage word leaked: {word}"


# ---------------------------------------------------------------------------
# spec §20 — 盘面共识一行 — day pool's heaviest-favorite tilt
# ---------------------------------------------------------------------------


def _signals(by_match: dict[str, MatchSignals]) -> PoolSignals:
    return PoolSignals(by_match=by_match, match_count=len(by_match))


def test_pool_consensus_heavy_favorite_day_at_or_below_1_80() -> None:
    """spec §20 — median min had ≤ HEAVY_FAVORITE_DAY_MAX → 大热门日."""
    signals = _signals({
        "周三001": MatchSignals(min_had_odds=1.94),
        "周三002": MatchSignals(min_had_odds=1.15),
        "周三003": MatchSignals(min_had_odds=1.34),
        "周三004": MatchSignals(min_had_odds=1.82),
        "周三005": MatchSignals(min_had_odds=1.25),
        "周三006": MatchSignals(min_had_odds=1.35),
        "周三007": MatchSignals(min_had_odds=1.67),
        "周三008": MatchSignals(min_had_odds=1.53),
        "周三009": MatchSignals(min_had_odds=1.35),
        "周三010": MatchSignals(min_had_odds=1.17),
        "周三011": MatchSignals(min_had_odds=2.05),
        "周三012": MatchSignals(min_had_odds=2.32),
    })
    line = pool_consensus(signals)
    assert "🟦 盘面共识" in line
    assert "12 场池" in line
    assert "大热门日" in line


def test_pool_consensus_balanced_day_between_thresholds() -> None:
    signals = _signals({
        "M1": MatchSignals(min_had_odds=1.95),
        "M2": MatchSignals(min_had_odds=2.05),
        "M3": MatchSignals(min_had_odds=2.30),
    })
    # median 2.05 → 1.80 < 2.05 ≤ 2.50 → 平衡日
    line = pool_consensus(signals)
    assert "平衡日" in line


def test_pool_consensus_upset_day_above_2_50() -> None:
    signals = _signals({
        "M1": MatchSignals(min_had_odds=2.55),
        "M2": MatchSignals(min_had_odds=2.80),
        "M3": MatchSignals(min_had_odds=3.30),
    })
    line = pool_consensus(signals)
    assert "上盘日" in line


def test_pool_consensus_empty_when_no_had_odds() -> None:
    """Empty by_match → renderer omits the line."""
    assert pool_consensus(PoolSignals()) == ""
    # by_match with all-zero min had odds also reads as no signal:
    signals = _signals({"M1": MatchSignals(min_had_odds=0.0)})
    assert pool_consensus(signals) == ""


def test_pool_consensus_thresholds_are_named_constants() -> None:
    """spec §20 — boundaries are documented constants, not magic literals."""
    assert HEAVY_FAVORITE_DAY_MAX == 1.80
    assert BALANCED_DAY_MAX == 2.50


def test_render_injects_pool_consensus_after_caveat_line() -> None:
    """The 盘面共识 line sits directly after the 混乱值越高 caveat."""
    signals = _signals({
        "M1": MatchSignals(min_had_odds=1.50),
        "M2": MatchSignals(min_had_odds=1.40),
        "M3": MatchSignals(min_had_odds=1.30),
    })
    plan = _plan(anchor=_anchor([]), tickets=[], pool_signals=signals)
    out = render_bold_plan(plan)
    lines = out.splitlines()
    caveat_idx = next(i for i, ln in enumerate(lines) if "混乱值越高" in ln)
    consensus_idx = next(i for i, ln in enumerate(lines) if "盘面共识" in ln)
    assert consensus_idx == caveat_idx + 1
    body = out[len(HARD_LABEL):]
    for word in _BANNED_WORDS:
        assert word not in body, f"advantage word leaked: {word}"


# ---------------------------------------------------------------------------
# spec §21 — 主题失谐 — theme picks vs pool consensus on theme direction
# ---------------------------------------------------------------------------


def _draw_bold_leg(match_no: str, *, pick_label: str = "1:1") -> BoldLeg:
    """A draw-lean bold leg — crs 1:1 by default (h==a is the draw-lean test)."""
    return BoldLeg(
        match_no=match_no, league="L", home="H", away="A",
        pick="s01s01", tc_odds=9.0, boldness=0.39,
        reason="比分 · 1:1 · 大胆腿",
        market="crs", pick_label=pick_label,
    )


def _draw_ticket(match_nos: tuple[str, ...]) -> BoldTicket:
    """A draw-majority ticket → classifies as 平局收割."""
    legs = [_draw_bold_leg(mn) for mn in match_nos]
    return BoldTicket(
        id="大胆票X", kind="大胆票", legs=legs,
        fold=len(legs), total_odds=9.0 ** len(legs),
        avg_boldness=0.39, note="",
    )


def test_theme_dissonance_5_20_case_draw_max_under_30pct() -> None:
    """spec §21 — 5/20 picked-leg draw implied: 003=0.235, 005=0.190, 006=0.208;
    max=0.235 < 0.30 → 平局收割 dissonant."""
    signals = _signals({
        "周三003": MatchSignals(draw_implied=0.235),
        "周三005": MatchSignals(draw_implied=0.190),
        "周三006": MatchSignals(draw_implied=0.208),
    })
    tickets = [_draw_ticket(("周三003", "周三005", "周三006"))]
    notices = theme_dissonance_notices(tickets, signals)
    assert len(notices) == 1
    assert "⚠️ 主题失谐" in notices[0]
    assert "平局收割" in notices[0]
    # 0.235 * 100 = 23.5 → :.0f banker-rounds to 24 (nearest-even).
    assert "24%" in notices[0]
    assert "反盘面挑冷" in notices[0]


def test_theme_dissonance_silent_when_a_picked_match_is_draw_competitive() -> None:
    """A single picked-leg match with draw implied ≥ 0.30 → theme resonant."""
    signals = _signals({
        "周三003": MatchSignals(draw_implied=0.235),
        "周三011": MatchSignals(draw_implied=0.303),    # competitive draw
        "周三006": MatchSignals(draw_implied=0.208),
    })
    tickets = [_draw_ticket(("周三003", "周三011", "周三006"))]
    assert theme_dissonance_notices(tickets, signals) == []


def test_theme_dissonance_high_goals_under_threshold() -> None:
    """进球狂欢 → max picked-leg ttg-≥3 implied must be ≥ 0.45."""
    signals = _signals({
        "M1": MatchSignals(high_goals_implied=0.30),
        "M2": MatchSignals(high_goals_implied=0.35),
    })
    legs = [
        BoldLeg(
            match_no=mn, league="L", home="H", away="A",
            pick="total_4", tc_odds=5.0, boldness=0.3,
            reason="总进球", market="ttg", pick_label="4球",
        )
        for mn in ("M1", "M2")
    ]
    ticket = BoldTicket(
        id="大胆票X", kind="大胆票", legs=legs,
        fold=2, total_odds=25.0, avg_boldness=0.3, note="",
    )
    notices = theme_dissonance_notices([ticket], signals)
    # ticket_theme: 2/2 legs are ttg market → 进球狂欢 theme
    assert len(notices) == 1
    assert "进球狂欢" in notices[0]
    assert "35%" in notices[0]


def test_theme_dissonance_silent_when_no_pool_signals() -> None:
    """Legacy callers / empty replay → empty list, never crash."""
    tickets = [_draw_ticket(("M1", "M2"))]
    assert theme_dissonance_notices(tickets, PoolSignals()) == []


def test_theme_dissonance_silent_when_no_tickets() -> None:
    signals = _signals({"M1": MatchSignals(draw_implied=0.10)})
    assert theme_dissonance_notices([], signals) == []


def test_theme_dissonance_thresholds_are_named_constants() -> None:
    assert THEME_DRAW_RESONANCE == 0.30
    assert THEME_HIGH_GOALS_RESONANCE == 0.45


# ---------------------------------------------------------------------------
# spec §22 — 翻面读法 — descriptive flip-reading hint at the bottom
# ---------------------------------------------------------------------------


def test_flip_reading_hint_fires_on_5_20_pattern() -> None:
    """spec §22 — heavy-favorite-day + low chaos + theme dissonant → render
    the descriptive flip-reading hint at the bottom."""
    signals = _signals({
        "周三003": MatchSignals(min_had_odds=1.34, draw_implied=0.235),
        "周三005": MatchSignals(min_had_odds=1.25, draw_implied=0.190),
        "周三006": MatchSignals(min_had_odds=1.35, draw_implied=0.208),
    })
    tickets = [_draw_ticket(("周三003", "周三005", "周三006"))]
    plan = _plan(
        anchor=_anchor([]), tickets=tickets,
        pool_signals=signals, day_chaos=8,
    )
    hint = flip_reading_hint(plan)
    assert "🎨 翻面读法" in hint
    assert "大热门日" in hint
    assert "平局收割" in hint
    assert "纯观察" in hint


def test_flip_reading_hint_silent_when_chaos_is_high() -> None:
    """Chaos > FLIP_READING_CHAOS_MAX → hint suppressed (not a calm day)."""
    signals = _signals({
        "M1": MatchSignals(min_had_odds=1.30, draw_implied=0.20),
        "M2": MatchSignals(min_had_odds=1.40, draw_implied=0.18),
    })
    tickets = [_draw_ticket(("M1", "M2"))]
    plan = _plan(
        anchor=_anchor([]), tickets=tickets,
        pool_signals=signals,
        day_chaos=FLIP_READING_CHAOS_MAX + 1,
    )
    assert flip_reading_hint(plan) == ""


def test_flip_reading_hint_silent_when_pool_is_not_heavy_favorite_day() -> None:
    """A balanced or upset day → consensus tilt isn't 大热门日 → no hint."""
    signals = _signals({
        "M1": MatchSignals(min_had_odds=2.20, draw_implied=0.20),
        "M2": MatchSignals(min_had_odds=2.40, draw_implied=0.18),
        "M3": MatchSignals(min_had_odds=2.60, draw_implied=0.17),
    })
    tickets = [_draw_ticket(("M1", "M2", "M3"))]
    plan = _plan(
        anchor=_anchor([]), tickets=tickets,
        pool_signals=signals, day_chaos=8,
    )
    assert flip_reading_hint(plan) == ""


def test_flip_reading_hint_silent_when_themes_resonate() -> None:
    """Heavy-favorite-day + a draw-competitive picked match → theme resonant
    → flip-hint suppressed."""
    signals = _signals({
        "M1": MatchSignals(min_had_odds=1.30, draw_implied=0.20),
        "M2": MatchSignals(min_had_odds=1.40, draw_implied=0.18),
        "M3": MatchSignals(min_had_odds=1.50, draw_implied=0.33),  # competitive
    })
    tickets = [_draw_ticket(("M1", "M2", "M3"))]
    plan = _plan(
        anchor=_anchor([]), tickets=tickets,
        pool_signals=signals, day_chaos=8,
    )
    assert flip_reading_hint(plan) == ""


def test_render_injects_flip_reading_hint_at_bottom() -> None:
    """The hint is appended after the closing 注金提示 line — strictly
    descriptive, banned-word safe."""
    signals = _signals({
        "周三003": MatchSignals(min_had_odds=1.34, draw_implied=0.235),
        "周三005": MatchSignals(min_had_odds=1.25, draw_implied=0.190),
        "周三006": MatchSignals(min_had_odds=1.35, draw_implied=0.208),
    })
    tickets = [_draw_ticket(("周三003", "周三005", "周三006"))]
    plan = _plan(
        anchor=_anchor([]), tickets=tickets,
        pool_signals=signals, day_chaos=8,
    )
    out = render_bold_plan(plan)
    lines = out.splitlines()
    closing_idx = next(i for i, ln in enumerate(lines) if "注金提示" in ln)
    flip_idx = next(i for i, ln in enumerate(lines) if "翻面读法" in ln)
    assert flip_idx > closing_idx
    body = out[len(HARD_LABEL):]
    for word in _BANNED_WORDS:
        assert word not in body, f"advantage word leaked: {word}"


# ---------------------------------------------------------------------------
# compute_pool_signals — pure-function harvest from BoldMatch list
# ---------------------------------------------------------------------------


def test_compute_pool_signals_extracts_min_had_and_draw_implied() -> None:
    """A match with had {1.34, 4.25, 6.75} → min=1.34, draw_implied=1/4.25."""
    match = _match(
        match_no="M1", tc_odds={"home": 1.34, "draw": 4.25, "away": 6.75},
    )
    signals = compute_pool_signals([match])
    assert signals.match_count == 1
    ms = signals.by_match["M1"]
    assert math.isclose(ms.min_had_odds, 1.34, abs_tol=1e-9)
    assert math.isclose(ms.draw_implied, 1.0 / 4.25, abs_tol=1e-9)


def test_compute_pool_signals_degrades_gracefully_with_no_ttg_or_hhad() -> None:
    """Markets that aren't quoted → 0.0 (signal unavailable, never crash)."""
    match = _match(
        match_no="M1", tc_odds={"home": 2.0, "draw": 3.4, "away": 3.8},
    )
    ms = compute_pool_signals([match]).by_match["M1"]
    assert ms.high_goals_implied == 0.0
    assert ms.underdog_let_implied == 0.0


# ---------------------------------------------------------------------------
# Integration — 5/20 replay scenario surfaces all four §19-§22 notices
# ---------------------------------------------------------------------------


def test_render_5_20_replay_surfaces_all_four_new_notices() -> None:
    """End-to-end: anchor + draw-only bold tickets + heavy-favorite pool
    signals + low chaos → render shows §19 同场反向, §20 大热门日, §21 主题失谐,
    §22 翻面读法. Banned-word safe across the entire body."""
    signals = _signals({
        "周三001": MatchSignals(min_had_odds=1.94),
        "周三002": MatchSignals(min_had_odds=1.15),
        "周三003": MatchSignals(min_had_odds=1.34, draw_implied=0.235),
        "周三005": MatchSignals(min_had_odds=1.25, draw_implied=0.190),
        "周三006": MatchSignals(min_had_odds=1.35, draw_implied=0.208),
    })
    anchor = _anchor([
        _anchor_leg("周三003", "home", "胜", 1.34),
        _anchor_leg("周三001", "away", "负", 1.94),
    ])
    bold_003 = BoldLeg(
        match_no="周三003", league="L", home="库奥皮奥", away="雅罗",
        pick="s01s01", tc_odds=9.0, boldness=0.39,
        reason="比分 · 1:1 · 大胆腿",
        market="crs", pick_label="1:1",
    )
    bold_005 = BoldLeg(
        match_no="周三005", league="L", home="利勒斯特", away="克里斯蒂",
        pick="draw", tc_odds=3.75, boldness=0.37,
        reason="让球 · 让平 · 大胆腿",
        market="hhad", pick_label="让平",
    )
    bold_006 = BoldLeg(
        match_no="周三006", league="L", home="赛哈海湾", away="吉达国民",
        pick="draw", tc_odds=3.63, boldness=0.39,
        reason="让球 · 让平 · 大胆腿",
        market="hhad", pick_label="让平",
    )
    ticket = BoldTicket(
        id="大胆票1", kind="大胆票",
        legs=[bold_003, bold_005, bold_006],
        fold=3, total_odds=9.0 * 3.75 * 3.63,
        avg_boldness=0.38, note="",
    )
    plan = _plan(
        anchor=anchor, tickets=[ticket],
        pool_signals=signals, day_chaos=8,
    )
    out = render_bold_plan(plan)
    assert "🟦 盘面共识" in out and "大热门日" in out          # §20
    assert "⚠️ 同场反向" in out and "周三003" in out           # §19
    assert "⚠️ 主题失谐" in out and "平局收割" in out          # §21
    assert "🎨 翻面读法" in out                                # §22
    body = out[len(HARD_LABEL):]
    for word in _BANNED_WORDS:
        assert word not in body, f"advantage word leaked: {word}"
