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
    HARD_LABEL,
    OUTCOMES,
    POOL_MAX,
    POOL_MIN,
    BoldComboEngine,
    BoldComboPlan,
    BoldLeg,
    BoldMatch,
    BoldTicket,
    anchor_ticket,
    bold_combos,
    bold_leg,
    boldness,
    chaos_band,
    chaos_pool_size,
    conflict_score,
    contrarian_score,
    day_chaos,
    dispersion_score,
    drift_score,
    heat_score,
    render_bold_plan,
)


def _match(
    *,
    match_no: str = "周日001",
    tc_odds: dict[str, float] | None = None,
    euro_odds: dict[str, float] | None = None,
    euro_opening: dict[str, float] | None = None,
    per_book_odds: dict[str, list[float]] | None = None,
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


def test_bold_combos_ranked_by_total_odds_times_avg_boldness() -> None:
    tickets = bold_combos(_legs(6), chaos=50)
    scores = [t.total_odds * t.avg_boldness for t in tickets]
    assert scores == sorted(scores, reverse=True)


def test_bold_combos_high_chaos_biases_toward_longer_tickets() -> None:
    calm = bold_combos(_legs(7), chaos=5)
    wild = bold_combos(_legs(7), chaos=95)

    calm_avg_fold = sum(t.fold for t in calm) / len(calm)
    wild_avg_fold = sum(t.fold for t in wild) / len(wild)
    assert wild_avg_fold > calm_avg_fold


def test_bold_combos_empty_when_too_few_legs() -> None:
    assert bold_combos(_legs(2), chaos=50) == []


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
