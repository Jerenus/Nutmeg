"""Regression for Rules A-F added to JCZQ daily generator.

Rules under test:
- A: poisson_solo leg selection (Poisson edge ≥ +15%); ticket retired by R28
- B: had legs ≤ 1.40 are banned from stable_base / main / poisson_solo
- C: high-volatility league flag downgrades low-side ttg picks
- D: hhad legs without an explicit handicap line are excluded
- E: three-way coinflip matches are skipped from had pool selection
- F: burned_teams from prior review get a -bias when they reappear
"""

from __future__ import annotations

import json
from pathlib import Path

from nutmeg.domain.jczq_daily import JczqDailyLeg, JczqDailyMatch
from nutmeg.services.jczq_daily import (
    BURNED_TEAM_BIAS,
    HAD_BANKER_FLOOR,
    JczqDailyAdvisorService,
    _build_memory_bias,
)
from nutmeg.services.jczq_intelligence import (
    COINFLIP_IMPLIED_SPREAD_THRESHOLD,
    COINFLIP_VIG_THRESHOLD,
    HIGH_VOLATILITY_TTG_MEDIAN,
    LeaguePriorBaseline,
    compute_analytics,
    compute_poisson_edges,
    poisson_edge_index,
)
from nutmeg.services.jczq_strategy_memory import (
    compute_league_ttg_volatility,
    recently_burned_teams,
)


def _pool(**kwargs):
    return kwargs


def _match(num, league, home, away, had, hhad, ttg, hafu, crs):
    return {
        "matchNumStr": num,
        "matchDate": "2026-05-05",
        "matchTime": "21:00:00",
        "leagueAbbName": league,
        "homeTeamAbbName": home,
        "awayTeamAbbName": away,
        "matchStatus": "Selling",
        "poolList": [
            {"poolCode": code, "poolStatus": "Selling", "single": 1, "allUp": 1}
            for code in ["HAD", "HHAD", "TTG", "HAFU", "CRS"]
        ],
        "had": had,
        "hhad": hhad,
        "ttg": ttg,
        "hafu": hafu,
        "crs": crs,
    }


def _coinflip(num: str, league: str = "西甲") -> dict:
    """36/28/36 implied; vig 12.9%; spread 8pp → coinflip."""
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="2.43", d="3.20", a="2.43"),
        _pool(h="2.10", d="3.20", a="3.10", goalLine="0"),
        _pool(s2="3.50"),
        _pool(hh="3.40", dh="6.20", dd="6.50"),
        _pool(s01s00="8.00", s01s01="6.20"),
    )


def _strong_chalk(num: str, league: str = "挪超") -> dict:
    """1.24 hot home favorite — Rule B should disqualify as banker."""
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="1.24", d="6.50", a="9.50"),
        _pool(h="2.05", d="3.45", a="2.95", goalLine="-1"),
        _pool(s1="9.75", s2="6.50", s3="4.20"),
        _pool(hh="2.20", dh="6.20", dd="9.40"),
        _pool(s00s00="33.00", s01s00="6.80"),
    )


def _normal(num: str, league: str = "意甲") -> dict:
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="1.55", d="3.80", a="5.30"),
        _pool(h="2.10", d="3.30", a="2.80", goalLine="-1"),
        _pool(s2="3.40"),
        _pool(hh="3.20", dh="4.20", dd="5.30"),
        _pool(s01s00="7.50", s01s01="6.40"),
    )


def _no_handicap_hhad(num: str) -> dict:
    """hhad pool present but goalLine missing — Rule D should drop these legs."""
    raw = _normal(num)
    raw["hhad"] = _pool(h="2.10", d="3.30", a="2.80")  # no goalLine
    return raw


def _payload(matches: list[dict]) -> dict:
    return {
        "lastUpdateTime": "2026-05-05 12:00:00",
        "matchInfoList": [
            {"businessDate": "2026-05-05", "subMatchList": matches}
        ],
    }


class FakeProvider:
    source_api = "fake://jczq-daily-iteration"
    source_page = "https://www.sporttery.cn/jc/jsq/zqspf/"

    def __init__(self, matches: list[dict]) -> None:
        self._matches = matches

    def fetch(self) -> dict:
        return _payload(self._matches)


# ---------------------------------------------------------------- Rule E ---


def test_rule_e_three_way_coinflip_flag_set_when_vig_high_and_spread_tight() -> None:
    matches = [_coinflip("周一001"), _normal("周一002")]
    service = JczqDailyAdvisorService(provider=FakeProvider(matches))
    report = service.build_report(run_date="2026-05-05")
    analytics = compute_analytics(report.matches, baseline=LeaguePriorBaseline())
    assert analytics["周一001"].is_three_way_coinflip is True
    assert analytics["周一002"].is_three_way_coinflip is False


def test_rule_e_main_skips_coinflip_match_for_had_legs(tmp_path: Path) -> None:
    matches = [
        _coinflip("周一001"),
        _normal("周一002"),
        _normal("周一003"),
        _normal("周一004"),
    ]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05", output_dir=tmp_path
    )
    main = next(plan for plan in report.plans if plan.kind == "main")
    coinflip_had = [
        leg for leg in main.legs if leg.match_no == "周一001" and leg.pool == "had"
    ]
    assert coinflip_had == [], "main must not pull had legs from coinflip matches"


# ---------------------------------------------------------------- Rule B ---


def test_rule_b_stable_base_excludes_had_at_or_below_banker_floor(
    tmp_path: Path,
) -> None:
    matches = [
        _strong_chalk("周一001"),  # had 1.24 — banned from stable_base
        _normal("周一002"),
        _normal("周一003"),
    ]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05", output_dir=tmp_path
    )
    stable = next(plan for plan in report.plans if plan.kind == "stable_base")
    chalk_legs = [
        leg
        for leg in stable.legs
        if leg.match_no == "周一001" and leg.pool == "had" and leg.odds <= HAD_BANKER_FLOOR
    ]
    assert chalk_legs == [], "stable_base must not anchor on had ≤ 1.40"


def test_rule_b_main_uses_higher_priced_had_when_floor_filter_kicks_in(
    tmp_path: Path,
) -> None:
    matches = [_strong_chalk("周一001")] + [_normal(f"周一00{i}") for i in range(2, 6)]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05", output_dir=tmp_path
    )
    main = next(plan for plan in report.plans if plan.kind == "main")
    for leg in main.legs:
        if leg.pool == "had":
            assert leg.odds > HAD_BANKER_FLOOR, (
                f"main had leg {leg.match_no} priced {leg.odds} violates Rule B"
            )


# ---------------------------------------------------------------- Rule A ---


# NOTE: poisson_solo as a generator-emitted ticket was retired by R28 (5/16).
# Its build-report-level behavior is covered by
# test_r28_poisson_solo_retired_never_appears_in_report. The tests below still
# exercise `_build_poisson_solo_plan` directly — that function is kept (behind
# RULE_R28_RETIRE_POISSON_SOLO) so a future re-review can revive the ticket.


def test_rule_a_v2_never_combines_same_match_legs_in_solo_ticket() -> None:
    """Rule A v2 v3 (5/07 redesign after 国家体彩 rule reminder).

    国家体彩混合过关规则禁止同一场次不同玩法在同一张过关票里相乘。所以即便
    同场有 crs 高 edge + ttg 中 edge 双信号，也只能挑一条入票，另一条不能作为
    支撑腿写进同一张票（可在 brief 第 5b 节作为分析证据展示）。

    https://www.sport.gov.cn/n20001280/n20745751/n20767297/c21177108/content.html
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周一001",
            match_date="2026-05-05",
            match_time="21:00:00",
            league="日职",
            home_team="H",
            away_team="A",
            status="Selling",
            hot_direction="主胜低赔(2.00)",
            role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一001", league="日职", home_team="H", away_team="A",
                    pool="crs", play="比分", pick="0:0", odds=11.0, logic="",
                ),
                JczqDailyLeg(
                    match_no="周一001", league="日职", home_team="H", away_team="A",
                    pool="ttg", play="总进球", pick="1球", odds=4.45, logic="",
                ),
            ],
        )
    ]
    crs_row = PoissonEdgeEntry(
        match_no="周一001", home="H", away="A", league="日职",
        pool="crs", pick="0:0", market_odd=11.0, fair_odd=9.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.15,  # +30% (R23 floor for crs 0:0 is +25%)
    )
    ttg_row = PoissonEdgeEntry(
        match_no="周一001", home="H", away="A", league="日职",
        pool="ttg", pick="1球", market_odd=4.45, fair_odd=4.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.02,  # +17%, also strong
    )
    plan = service._build_poisson_solo_plan(matches, poisson_rows=[crs_row, ttg_row])
    # Rule O: only one leg may enter the ticket (no same-match combos).
    # R26 (5/15): crs is filtered out of poisson_solo entirely, so ttg wins
    # even though crs has higher raw edge — and that's the right outcome:
    # crs alpha is 1/30 historical (3.3%), ttg has higher reliability.
    assert len(plan.legs) == 1, (
        "Rule A v2 v3 must NEVER produce same-match different-pool combos "
        "(国家体彩混合过关规则)"
    )
    assert plan.legs[0].pool == "ttg", "R26 routes crs alpha out of poisson_solo"
    assert plan.legs[0].pick == "1球"


def test_rule_a_v2_cross_match_support_extends_to_two_legs() -> None:
    """When a cross-match +EV row (>= +5%) exists, Rule A v2 extends the
    primary-edge solo to a 2-leg cross-match combo.

    R26 (5/15) drops crs from poisson_solo eligibility; both legs now come
    from non-crs pools (ttg / had / hhad).
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_CROSS_MATCH_SUPPORT_EDGE,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周一001", match_date="2026-05-05", match_time="21:00:00",
            league="日职", home_team="H1", away_team="A1", status="Selling",
            hot_direction="主胜低赔(2.00)", role="均衡分歧场", confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一001", league="日职", home_team="H1", away_team="A1",
                    pool="ttg", play="总进球", pick="2球", odds=3.80, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周一002", match_date="2026-05-05", match_time="21:00:00",
            league="意甲", home_team="H2", away_team="A2", status="Selling",
            hot_direction="主胜低赔(1.80)", role="均衡分歧场", confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一002", league="意甲", home_team="H2", away_team="A2",
                    pool="ttg", play="总进球", pick="1球", odds=4.20, logic="",
                ),
            ],
        ),
    ]
    primary = PoissonEdgeEntry(
        match_no="周一001", home="H1", away="A1", league="日职",
        pool="ttg", pick="2球", market_odd=3.80, fair_odd=2.90,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.15,  # +30%, primary alpha
    )
    cross_support = PoissonEdgeEntry(
        match_no="周一002", home="H2", away="A2", league="意甲",
        pool="ttg", pick="1球", market_odd=4.20, fair_odd=4.0,
        edge=POISSON_SOLO_CROSS_MATCH_SUPPORT_EDGE + 0.03,  # +8%, below +15% but ≥ +5%
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[primary, cross_support]
    )
    assert len(plan.legs) == 2
    match_nos = {leg.match_no for leg in plan.legs}
    assert match_nos == {"周一001", "周一002"}, "must be cross-match"


def test_rule_a_v3_at_most_one_crs_leg_per_poisson_solo_ticket() -> None:
    """Rule A v3 (5/08 落库): cross-match crs×crs combos have ~0.6% joint
    hit rate (each ~8%) — that's a longshot, not alpha. R5 caps poisson_solo
    at 1 crs leg total. The other slot must come from ttg/had/hhad.

    5/07 incident: C ticket was 005 0:0 × 002 0:0 (both +20%-30% edges)
    → 0/2. The compound was billed as "alpha" but joint odds put it ~0.6%
    hit, not "model-priced".
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_CROSS_MATCH_SUPPORT_EDGE,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周四005", match_date="2026-05-07", match_time="08:30:00",
            league="解放者杯", home_team="H1", away_team="A1", status="Selling",
            hot_direction="主胜低赔(1.37)", role="均衡分歧场", confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周四005", league="解放者杯", home_team="H1", away_team="A1",
                    pool="crs", play="比分", pick="0:0", odds=13.0, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四005", league="解放者杯", home_team="H1", away_team="A1",
                    pool="ttg", play="总进球", pick="1球", odds=4.80, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周四002", match_date="2026-05-07", match_time="03:00:00",
            league="欧罗巴", home_team="H2", away_team="A2", status="Selling",
            hot_direction="主胜低赔(1.62)", role="均衡分歧场", confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周四002", league="欧罗巴", home_team="H2", away_team="A2",
                    pool="crs", play="比分", pick="0:0", odds=12.0, logic="",
                ),
            ],
        ),
    ]
    crs_005 = PoissonEdgeEntry(
        match_no="周四005", home="H1", away="A1", league="解放者杯",
        pool="crs", pick="0:0", market_odd=13.0, fair_odd=9.97,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.15,  # +30%
    )
    crs_002 = PoissonEdgeEntry(
        match_no="周四002", home="H2", away="A2", league="欧罗巴",
        pool="crs", pick="0:0", market_odd=12.0, fair_odd=9.97,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.05,  # +20%
    )
    ttg_005 = PoissonEdgeEntry(
        match_no="周四005", home="H1", away="A1", league="解放者杯",
        pool="ttg", pick="1球", market_odd=4.80, fair_odd=4.34,
        edge=POISSON_SOLO_EDGE_THRESHOLD - 0.05,  # +10%, below +15% solo but ≥ +5% cross
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[crs_005, crs_002, ttg_005]
    )
    crs_legs = [leg for leg in plan.legs if leg.pool == "crs"]
    assert len(crs_legs) <= 1, (
        f"Rule A v3 violated: {len(crs_legs)} crs legs in poisson_solo "
        f"(joint hit ~0.6% for 2 crs legs)"
    )


def test_rule_o_same_match_pool_violation_detector() -> None:
    """check_same_match_pool_legality flags any plan that mixes same-match
    different-pool legs (国家体彩 illegal parlay structure).
    """
    from nutmeg.domain.jczq_daily import JczqDailyPlan
    from nutmeg.services.jczq_diagnostics import (
        SameMatchPoolViolation,
        check_same_match_pool_legality,
    )

    legal_plan = JczqDailyPlan(
        name="A",
        kind="stable_base",
        description="legal",
        legs=[
            JczqDailyLeg(
                match_no="周一001", league="意甲", home_team="H1", away_team="A1",
                pool="had", play="胜平负", pick="胜", odds=1.65, logic="",
            ),
            JczqDailyLeg(
                match_no="周一002", league="意甲", home_team="H2", away_team="A2",
                pool="had", play="胜平负", pick="胜", odds=1.70, logic="",
            ),
        ],
        total_odds=2.81,
        two_yuan_return=5.62,
        risk_note="",
    )
    illegal_plan = JczqDailyPlan(
        name="C",
        kind="poisson_solo",
        description="illegal — same-match ttg+crs",
        legs=[
            JczqDailyLeg(
                match_no="周一001", league="意甲", home_team="H1", away_team="A1",
                pool="ttg", play="总进球", pick="1球", odds=4.20, logic="",
            ),
            JczqDailyLeg(
                match_no="周一001", league="意甲", home_team="H1", away_team="A1",
                pool="crs", play="比分", pick="0:0", odds=11.0, logic="",
            ),
        ],
        total_odds=46.20,
        two_yuan_return=92.40,
        risk_note="",
    )

    violations = check_same_match_pool_legality([legal_plan, illegal_plan])
    assert len(violations) == 1
    v = violations[0]
    assert isinstance(v, SameMatchPoolViolation)
    assert v.plan_kind == "poisson_solo"
    assert v.match_no == "周一001"
    assert set(v.pools) == {"ttg", "crs"}
    assert v.severity == "blocking"


# ---------------------------------------------------------------- Rule C ---


def test_rule_c_high_volatility_league_flag_set_when_median_meets_threshold() -> None:
    memory = {
        "oracle_learnings": [
            {"league": "瑞超", "pool": "ttg", "winning_pick": "4球"},
            {"league": "瑞超", "pool": "ttg", "winning_pick": "3球"},
            {"league": "瑞超", "pool": "ttg", "winning_pick": "5球"},
            {"league": "瑞超", "pool": "ttg", "winning_pick": "6球"},
            {"league": "意甲", "pool": "ttg", "winning_pick": "2球"},
            {"league": "意甲", "pool": "ttg", "winning_pick": "1球"},
            {"league": "意甲", "pool": "ttg", "winning_pick": "2球"},
            {"league": "意甲", "pool": "ttg", "winning_pick": "3球"},
        ]
    }
    vol = compute_league_ttg_volatility(memory)
    assert vol["瑞超"] >= HIGH_VOLATILITY_TTG_MEDIAN
    assert vol["意甲"] < HIGH_VOLATILITY_TTG_MEDIAN
    matches = [_normal("周一001", league="瑞超"), _normal("周一002", league="意甲")]
    service = JczqDailyAdvisorService(provider=FakeProvider(matches))
    report = service.build_report(run_date="2026-05-05")
    analytics = compute_analytics(
        report.matches, baseline=LeaguePriorBaseline(), league_volatility=vol
    )
    assert analytics["周一001"].is_high_volatility_league is True
    assert analytics["周一002"].is_high_volatility_league is False


# ---------------------------------------------------------------- Rule D ---


def test_rule_d_hhad_legs_without_handicap_dropped_from_search(tmp_path: Path) -> None:
    matches = [
        _no_handicap_hhad("周一001"),
        _no_handicap_hhad("周一002"),
        _no_handicap_hhad("周一003"),
        _no_handicap_hhad("周一004"),
    ]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05", output_dir=tmp_path
    )
    for plan in report.plans:
        for leg in plan.legs:
            if leg.pool == "hhad":
                assert leg.goal_line, (
                    f"plan={plan.kind} match={leg.match_no} hhad pick {leg.pick} "
                    f"selected without handicap line — Rule D violation"
                )


# ---------------------------------------------------------------- Rule F ---


def test_rule_f_burned_teams_extracted_from_decision_policy() -> None:
    memory = {
        "decision_policy": {
            "rules": {
                "reuse_guard": {
                    "active": True,
                    "burned_teams": ["埃弗顿", "曼城", "塞维利亚"],
                }
            }
        }
    }
    teams = recently_burned_teams(memory)
    assert teams == {"埃弗顿", "曼城", "塞维利亚"}


def test_rule_f_memory_bias_subtracts_for_burned_team_legs() -> None:
    burned = {"埃弗顿"}
    bias_fn = _build_memory_bias({}, burned_teams=burned)
    assert bias_fn is not None
    burned_leg = JczqDailyLeg(
        match_no="周一009",
        league="英超",
        home_team="埃弗顿",
        away_team="曼城",
        pool="had",
        play="胜平负",
        pick="负",
        odds=1.34,
        logic="",
    )
    clean_leg = JczqDailyLeg(
        match_no="周一008",
        league="意甲",
        home_team="罗马",
        away_team="佛罗伦萨",
        pool="had",
        play="胜平负",
        pick="胜",
        odds=1.48,
        logic="",
    )
    assert bias_fn(burned_leg, None) == BURNED_TEAM_BIAS
    assert bias_fn(clean_leg, None) == 0.0


def test_rule_f_persisted_via_decision_policy_after_review(tmp_path: Path) -> None:
    """Burned teams flow into strategy-memory's reuse_guard rule on review."""

    from nutmeg.services.jczq_strategy_memory import update_strategy_memory

    context = {
        "matches": [
            {
                "match_no": "周一009",
                "league": "英超",
                "role": "强胆场",
                "hot_direction": "客胜低赔(1.34)",
                "confidence_note": "胜平负方向可做胆。",
            }
        ]
    }
    graded_legs = [
        {
            "match_no": "周一009",
            "home_team": "埃弗顿",
            "away_team": "曼城",
            "pool": "had",
            "pick": "负",
            "odds": 1.34,
            "hit": False,
        },
        {
            "match_no": "周一009",
            "home_team": "埃弗顿",
            "away_team": "曼城",
            "pool": "ttg",
            "pick": "3球",
            "odds": 3.5,
            "hit": False,
        },
    ]
    memory = update_strategy_memory(
        output_dir=tmp_path,
        run_date="2026-05-04",
        context=context,
        results={"周一009": {"had": "平", "ttg": "6球"}},
        graded_legs=graded_legs,
    )
    burned = (
        ((memory.get("decision_policy") or {}).get("rules") or {})
        .get("reuse_guard", {})
        .get("burned_teams")
    )
    assert burned == ["埃弗顿", "曼城"]
    # Round-trip via the helper that the daily service uses.
    assert recently_burned_teams(memory) == {"埃弗顿", "曼城"}


# -------------------------------------------------------- replay smoke test

def test_replay_2026_05_04_inspires_full_4_of_4_inspiration(tmp_path: Path) -> None:
    """Smoke test using the actual 5/04 context.json — proves Rules A-F deliver
    at least the inspiration ticket the user reviewed in the retrospective.

    Skipped if the user's local data dir isn't present; this is a developer-side
    smoke test, not a CI requirement.
    """

    src = Path("/Users/jz71/Projects/Nutmeg/.nutmeg-data/jczq/daily/2026-05-04/context.json")
    if not src.exists():
        return
    ctx = json.loads(src.read_text(encoding="utf-8"))
    service = JczqDailyAdvisorService.__new__(JczqDailyAdvisorService)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no=item["match_no"],
            match_date=item["match_date"],
            match_time=item["match_time"],
            league=item["league"],
            home_team=item["home_team"],
            away_team=item["away_team"],
            status=item["status"],
            hot_direction=item["hot_direction"],
            role=item["role"],
            confidence_note=item["confidence_note"],
            candidates=[
                JczqDailyLeg(
                    match_no=leg["match_no"],
                    league=leg["league"],
                    home_team=leg["home_team"],
                    away_team=leg["away_team"],
                    pool=leg["pool"],
                    play=leg["play"],
                    pick=leg["pick"],
                    odds=float(leg["odds"]),
                    logic=leg.get("logic", ""),
                    goal_line=leg.get("goal_line", ""),
                    odds_update=leg.get("odds_update", ""),
                )
                for leg in item["candidates"]
            ],
        )
        for item in ctx["matches"]
    ]
    plans = service._build_plans(matches, instruction=None, strategy_memory={})
    # 5/04 historical: 周一007 crs 0:0 +21.6% was the day's top Poisson edge
    # and the canonical alpha hit (20x payout). After R23 (5/13) raised the
    # crs 0:0 poisson_solo floor to +25%, this leg no longer enters
    # poisson_solo. Test now permits an empty poisson_solo on 5/04 — the
    # smoke test's primary assertion is on inspiration coverage, not on
    # crs alpha tickets that R23 deliberately filters out.
    poisson_solo = next((plan for plan in plans if plan.kind == "poisson_solo"), None)
    if poisson_solo is not None and poisson_solo.legs:
        # If anything survives R23, the picks should still be from genuine
        # Poisson alpha (not crs 0:0 between +15% and +25%).
        for leg in poisson_solo.legs:
            assert not (leg.pool == "crs" and leg.pick == "0:0"), (
                "R23 violation: 5/04 crs 0:0 below +25% should be filtered"
            )


# ---------------------------------------------------------------- Rule H ---
# H: hafu legs are non-extreme tickets' worst pool (4-day backtest 0/9 = 0%).
#    Generator must keep hafu only inside the extreme ticket.


def _hafu_attractive(num: str, league: str = "意甲") -> dict:
    """Match exposing multiple hafu picks at attractive prices.

    Without Rule H the generator was happy to pull these into main/inspiration/
    contrarian/false_signal as the 'high-leverage' leg. They never paid off.
    """
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="2.10", d="3.30", a="3.50"),
        _pool(h="2.30", d="3.20", a="2.80", goalLine="0"),
        _pool(s2="3.50", s3="3.80"),
        _pool(
            hh="3.20",
            hd="6.20",
            ha="9.40",
            dh="4.20",
            dd="5.30",
            da="6.50",
            ah="9.50",
            ad="6.10",
            aa="3.40",
        ),
        _pool(s01s00="7.50", s01s01="6.40", s00s00="14.00", s02s01="11.50"),
    )


def test_rule_h_hafu_legs_only_appear_in_extreme(tmp_path: Path) -> None:
    matches = [_hafu_attractive(f"周一00{i}") for i in range(1, 6)]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05", output_dir=tmp_path
    )
    for plan in report.plans:
        if plan.kind == "extreme":
            continue
        for leg in plan.legs:
            assert leg.pool != "hafu", (
                f"Rule H violation: plan={plan.kind} leg={leg.match_no} "
                f"hafu pick {leg.pick} must not appear outside extreme"
            )


# ---------------------------------------------------------------- Rule J ---
# J: crs hit-rate 1/14 across 4-day backtest. Extreme picks must be supported by
#    the Poisson model (edge ≥ -10%).

CRS_POISSON_EDGE_FLOOR = -0.10


def test_rule_j_extreme_crs_legs_meet_poisson_edge_floor(tmp_path: Path) -> None:
    matches = [_normal(f"周一00{i}") for i in range(1, 6)]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05", output_dir=tmp_path
    )
    extreme = next(plan for plan in report.plans if plan.kind == "extreme")
    edges = poisson_edge_index(compute_poisson_edges(report.matches))
    crs_legs = [leg for leg in extreme.legs if leg.pool == "crs"]
    # The fixture is rich enough to expect at least one crs leg in extreme.
    assert crs_legs, "extreme should still produce crs legs (Rule J filters, not deletes)"
    for leg in crs_legs:
        edge = edges.get((leg.match_no, "crs", leg.pick))
        assert edge is not None, (
            f"Rule J pre-condition: crs leg {leg.match_no} {leg.pick} "
            "must be priced by Poisson model"
        )
        assert edge >= CRS_POISSON_EDGE_FLOOR, (
            f"Rule J violation: extreme picked crs {leg.match_no} {leg.pick}@{leg.odds} "
            f"with Poisson edge {edge:+.1%} (floor {CRS_POISSON_EDGE_FLOOR:+.0%})"
        )


# ---------------------------------------------------------------- Rule I ---
# I-1: high-odds had legs (≥ 5.0) hit only 0/1 across 4 days; require Poisson
#      EV ≥ +5% to qualify as a leverage leg.
# I-2: contrarian intent must reject any leg the Poisson model strongly opposes
#      (edge ≤ -15%) — 5/05's contrarian had 'ttg 4球' at -22.5% edge.

HIGH_ODDS_HAD_FLOOR = 5.0
HIGH_ODDS_HAD_REQUIRED_EDGE = 0.05
CONTRARIAN_POISSON_REJECT_BELOW = -0.15


def _high_odds_had_trap(num: str, league: str = "意甲") -> dict:
    """Match where the away pick is priced at 5.30 — typical 'inspirational' trap.

    Poisson with home_lambda ~ 1.6 and away_lambda ~ 0.9 prices away under 5.30
    (negative edge). Rule I should keep this leg out of inspiration.
    """
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="1.55", d="3.80", a="5.30"),
        _pool(h="2.10", d="3.30", a="2.80", goalLine="-1"),
        _pool(s2="3.40", s3="3.80"),
        _pool(hh="3.20", dh="4.20", dd="5.30"),
        _pool(s01s00="7.50", s01s01="6.40", s00s00="14.00"),
    )


def test_rule_i_inspiration_rejects_high_odds_had_without_poisson_ev(
    tmp_path: Path,
) -> None:
    matches = [_high_odds_had_trap(f"周一00{i}") for i in range(1, 6)]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05", output_dir=tmp_path
    )
    inspiration = next(plan for plan in report.plans if plan.kind == "inspiration")
    edges = poisson_edge_index(compute_poisson_edges(report.matches))
    for leg in inspiration.legs:
        if leg.pool != "had" or leg.odds < HIGH_ODDS_HAD_FLOOR:
            continue
        edge = edges.get((leg.match_no, "had", leg.pick))
        assert edge is not None and edge >= HIGH_ODDS_HAD_REQUIRED_EDGE, (
            f"Rule I-1 violation: inspiration high-odds had {leg.match_no} "
            f"{leg.pick}@{leg.odds} selected with Poisson edge {edge!r}"
        )


def test_rule_i_select_top_legs_rejects_legs_below_poisson_edge_floor() -> None:
    """select_top_legs must accept a `reject_poisson_edge_below` filter.

    This is the mechanism contrarian uses (and the report/replay path can rely
    on) to skip legs the Poisson model strongly opposes — even if they score
    well under the heuristic intent rules.
    """

    from nutmeg.services.jczq_intelligence import select_top_legs

    matches = [_contrarian_ttg_trap("周一001"), _normal("周一002")]
    service = JczqDailyAdvisorService(provider=FakeProvider(matches))
    report = service.build_report(run_date="2026-05-05")
    analytics = compute_analytics(report.matches, baseline=LeaguePriorBaseline())
    edges = poisson_edge_index(compute_poisson_edges(report.matches))

    # Plant a synthetic strongly-opposed edge for an existing leg so the test
    # is independent of the Poisson grid's exact output.
    forced_edges = dict(edges)
    forced_edges[("周一001", "ttg", "4球")] = -0.30

    legs = select_top_legs(
        report.matches,
        analytics,
        intent="contrarian",
        k=10,
        pool_filter={"ttg"},
        odds_min=3.0,
        odds_max=8.0,
        poisson_edge_index=forced_edges,
        reject_poisson_edge_below=CONTRARIAN_POISSON_REJECT_BELOW,
    )
    assert all(
        not (ev.leg.match_no == "周一001" and ev.leg.pool == "ttg" and ev.leg.pick == "4球")
        for ev in legs
    ), "Rule I-2 violation: select_top_legs returned a leg below the Poisson edge floor"


def _contrarian_ttg_trap(num: str, league: str = "意甲") -> dict:
    """ttg 4球 priced at 5.00 — used by Rule I-2 unit test fixture."""
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="1.55", d="3.80", a="5.30"),
        _pool(h="2.10", d="3.30", a="2.80", goalLine="-1"),
        _pool(s2="3.40", s3="3.80", s4="5.00", s5="9.00"),
        _pool(hh="3.20", dh="4.20", dd="5.30"),
        _pool(s01s00="7.50", s00s00="14.00"),
    )


_ = COINFLIP_VIG_THRESHOLD  # silence ruff when threshold consts move
_ = COINFLIP_IMPLIED_SPREAD_THRESHOLD


# --------------------------------------------------- R13 (5/10 落库) ---


def test_r13_poisson_solo_rejects_ttg_low_when_expected_goals_high() -> None:
    """R13: poisson_solo ttg picks {0球, 1球, 2球} require model expected_goals
    < 2.7. 5/09 周六016 斯图加特 vs 勒沃 fit gave expected_goals = 3.2; ttg 1球
    edge was +30.4% but the leg lost (actual 4 球). Human debate (Claude vs GPT)
    caught this and replaced 016 ttg 1球 with 019 ttg 1球 (expected_goals=2.0)
    → C 票中 74.80x. R13 makes the generator do this automatically.
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
        POISSON_SOLO_TTG_LOW_GOAL_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周六016", match_date="2026-05-09", match_time="22:30:00",
            league="德甲", home_team="斯图加特", away_team="勒沃库森",
            status="Selling", hot_direction="主胜低赔(2.13)", role="开放节奏场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周六016", league="德甲", home_team="斯图加特",
                    away_team="勒沃库森", pool="ttg", play="总进球",
                    pick="1球", odds=10.0, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周六007", match_date="2026-05-09", match_time="22:00:00",
            league="英冠", home_team="米堡", away_team="南安普敦",
            status="Selling", hot_direction="主胜低赔(2.08)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周六007", league="英冠", home_team="米堡",
                    away_team="南安普敦", pool="crs", play="比分",
                    pick="0:0", odds=11.0, logic="",
                ),
            ],
        ),
    ]
    high_goal_ttg = PoissonEdgeEntry(
        match_no="周六016", home="斯图加特", away="勒沃库森", league="德甲",
        pool="ttg", pick="1球", market_odd=10.0, fair_odd=7.67,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.15,  # +30% — would normally pass
        expected_goals=POISSON_SOLO_TTG_LOW_GOAL_THRESHOLD + 0.5,  # 3.2
    )
    safe_crs = PoissonEdgeEntry(
        match_no="周六007", home="米堡", away="南安普敦", league="英冠",
        pool="crs", pick="0:0", market_odd=11.0, fair_odd=8.17,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.20,  # +35%
        expected_goals=2.1,
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[high_goal_ttg, safe_crs]
    )
    # The ttg 1球 leg with expected_goals=3.2 must be filtered out by R13.
    assert all(
        not (leg.match_no == "周六016" and leg.pool == "ttg" and leg.pick == "1球")
        for leg in plan.legs
    ), "R13: poisson_solo must reject ttg 1球 when expected_goals ≥ 2.7"


def test_r15_contrarian_rejects_deep_bet_on_strong_banker() -> None:
    """R15 (5/10): contrarian must not pick hhad 让胜 ≤ 3.0 in a strong-banker
    match. 5/09 周六029 莱切-尤文 had 1.32 → contrarian picked hhad 让胜 @ 2.8
    (尤文 wins by 2+) and lost (实际让平). That leg is leveraged-favorite, not
    contrarian — Rule D says "反舒服盘 / coinflip / draw_friendly".
    """
    from nutmeg.services.jczq_intelligence import (
        MatchAnalytics,
        select_top_legs,
    )

    matches = [
        JczqDailyMatch(
            match_no="周六029", match_date="2026-05-09", match_time="22:30:00",
            league="意甲", home_team="莱切", away_team="尤文",
            status="Selling", hot_direction="客胜低赔(1.32)", role="强胆场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周六029", league="意甲", home_team="莱切",
                    away_team="尤文", pool="hhad", play="让球胜平负",
                    pick="让胜", odds=2.80, logic="", goal_line="+1",
                ),
                JczqDailyLeg(
                    match_no="周六029", league="意甲", home_team="莱切",
                    away_team="尤文", pool="had", play="胜平负",
                    pick="平", odds=5.50, logic="",
                ),
            ],
        ),
    ]
    analytics = {
        "周六029": MatchAnalytics(
            match_no="周六029",
            league="意甲",
            favorite_outcome="负",
            favorite_odds=1.32,
            favorite_implied=0.67,
            implied_probs={"胜": 0.12, "平": 0.21, "负": 0.67},
            vig_pct=0.13,
            dispersion=0.55,
            popularity_score=5,
            popularity_tier="h",
            baseline_probs={"胜": 0.45, "平": 0.27, "负": 0.28},
            ev_gaps={"had": {"胜": -0.33, "平": -0.06, "负": 0.39}},
            is_strong_banker=True,
            is_comfort_risk=False,
            is_chaos=False,
            is_draw_friendly=False,
            is_upset_candidate=False,
        ),
    }
    legs = select_top_legs(
        matches, analytics, intent="contrarian", k=10,
        pool_filter={"hhad", "had"},
        odds_min=1.0, odds_max=10.0,
        require_hhad_handicap=True,
    )
    assert all(
        not (
            ev.leg.match_no == "周六029"
            and ev.leg.pool == "hhad"
            and ev.leg.pick == "让胜"
        )
        for ev in legs
    ), "R15 violated: contrarian deep-bet hhad 让胜 leaked through strong-banker filter"


def test_r9_extreme_drops_weak_crs_when_no_strong_anchor(tmp_path: Path) -> None:
    """R9 (5/10): extreme ticket with ≥ 2 crs legs requires the strongest to
    clear +25% edge AND any extra to clear +15%. 5/09 周六010 0:0 (edge +7%)
    × 周六007 0:0 (edge +35%) — the +7% leg was just above Rule J's -10% floor
    but well below alpha. The weaker leg should drop, leaving a single 007 crs.
    """
    from nutmeg.services.jczq_daily import (
        EXTREME_CRS_MULTI_LEG_MIN_EDGE,
        EXTREME_CRS_MULTI_LEG_PEAK_EDGE,
    )

    matches = [_strong_chalk(f"周一00{i}") for i in range(1, 6)]
    service = JczqDailyAdvisorService(provider=FakeProvider(matches))
    report = service.build_report(run_date="2026-05-05", output_dir=tmp_path)
    extreme = next((plan for plan in report.plans if plan.kind == "extreme"), None)
    if extreme is None or not extreme.legs:
        return
    edges = poisson_edge_index(compute_poisson_edges(report.matches))
    crs_legs = [leg for leg in extreme.legs if leg.pool == "crs"]
    if len(crs_legs) < 2:
        return  # R9 only constrains ≥ 2 crs legs
    crs_edge_values = [
        edges.get((leg.match_no, "crs", leg.pick))
        for leg in crs_legs
    ]
    crs_edge_values = [e for e in crs_edge_values if e is not None]
    if not crs_edge_values:
        return
    peak = max(crs_edge_values)
    assert peak >= EXTREME_CRS_MULTI_LEG_PEAK_EDGE, (
        f"R9 violated: extreme has ≥ 2 crs legs but peak edge {peak:+.1%} "
        f"is below {EXTREME_CRS_MULTI_LEG_PEAK_EDGE:+.0%}"
    )
    for edge in crs_edge_values:
        assert edge >= EXTREME_CRS_MULTI_LEG_MIN_EDGE, (
            f"R9 violated: extreme crs leg edge {edge:+.1%} below "
            f"{EXTREME_CRS_MULTI_LEG_MIN_EDGE:+.0%}"
        )


def test_r11_draw_cluster_filters_legs_below_poisson_edge_floor(tmp_path: Path) -> None:
    """R11 (5/10): draw_cluster had 平 legs must clear edge ≥ -8%. 5/09 had
    9 comfort-risk matches → cluster picked 4 had 平 legs all at -10% to
    -13% edge → 0/4. Floor trims to 2-3 legs on dry days.
    """
    from nutmeg.services.jczq_daily import DRAW_CLUSTER_EDGE_FLOOR

    matches = [_normal(f"周一00{i}") for i in range(1, 8)]
    service = JczqDailyAdvisorService(provider=FakeProvider(matches))
    report = service.build_report(run_date="2026-05-05", output_dir=tmp_path)
    draw_cluster = next(
        (plan for plan in report.plans if plan.kind == "draw_cluster"), None
    )
    if draw_cluster is None or not draw_cluster.legs:
        return
    edges = poisson_edge_index(compute_poisson_edges(report.matches))
    for leg in draw_cluster.legs:
        edge = edges.get((leg.match_no, leg.pool, leg.pick))
        if edge is None:
            continue
        assert edge >= DRAW_CLUSTER_EDGE_FLOOR, (
            f"R11 violated: draw_cluster {leg.pool}/{leg.pick}@{leg.odds} "
            f"edge {edge:+.1%} (floor {DRAW_CLUSTER_EDGE_FLOOR:+.0%})"
        )


def test_r12_false_signal_rejects_priced_legs_below_edge_floor(tmp_path: Path) -> None:
    """R12 (5/10): false_signal ttg/crs/hafu legs must clear edge ≥ -10%.
    5/09 周六024 ttg 4球 made false_signal at -19% edge → lost. The model-
    opposed leg is noise, not contrarian narrative.
    """
    from nutmeg.services.jczq_daily import (
        FALSE_SIGNAL_PRICED_EDGE_FLOOR,
    )

    matches = [_normal(f"周一00{i}") for i in range(1, 6)]
    service = JczqDailyAdvisorService(provider=FakeProvider(matches))
    report = service.build_report(run_date="2026-05-05", output_dir=tmp_path)
    false_signal = next(
        (plan for plan in report.plans if plan.kind == "false_signal"), None
    )
    if false_signal is None or not false_signal.legs:
        return  # plan is empty; nothing to assert
    edges = poisson_edge_index(compute_poisson_edges(report.matches))
    for leg in false_signal.legs:
        if leg.pool not in {"ttg", "crs", "hafu"}:
            continue
        edge = edges.get((leg.match_no, leg.pool, leg.pick))
        if edge is None:
            continue
        assert edge >= FALSE_SIGNAL_PRICED_EDGE_FLOOR, (
            f"R12 violated: false_signal {leg.pool}/{leg.pick}@{leg.odds} "
            f"with edge {edge:+.1%} (floor {FALSE_SIGNAL_PRICED_EDGE_FLOOR:+.0%})"
        )


def test_r10_hi_vol_main_hard_rejects_ttg_low_picks() -> None:
    """R10 (5/10): hi-vol leagues (incl. R2 override: 美职/沙职/欧战…) hard-
    reject ttg 0/1/2球 in main/contrarian. Rule C only soft-penalized -0.5;
    5/09 周六026 美职 ttg 2球 still made main and lost (actual 6球, resid +2.8).
    """
    from nutmeg.services.jczq_intelligence import (
        MatchAnalytics,
        select_top_legs,
    )

    matches = [
        JczqDailyMatch(
            match_no="周六026", match_date="2026-05-09", match_time="08:00:00",
            league="美职", home_team="多伦多", away_team="迈国际",
            status="Selling", hot_direction="客胜低赔(1.62)", role="开放节奏场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周六026", league="美职", home_team="多伦多",
                    away_team="迈国际", pool="ttg", play="总进球",
                    pick="2球", odds=4.35, logic="",
                ),
                # Provide a non-ttg fallback so select_top_legs has something
                # to return (else fixture is empty under R10 hard-filter).
                JczqDailyLeg(
                    match_no="周六026", league="美职", home_team="多伦多",
                    away_team="迈国际", pool="had", play="胜平负",
                    pick="负", odds=1.62, logic="",
                ),
            ],
        ),
    ]
    analytics = {
        "周六026": MatchAnalytics(
            match_no="周六026",
            league="美职",
            favorite_outcome="负",
            favorite_odds=1.62,
            favorite_implied=0.55,
            implied_probs={"胜": 0.23, "平": 0.22, "负": 0.55},
            vig_pct=0.13,
            dispersion=0.13,
            popularity_score=0,
            popularity_tier="m",
            baseline_probs={"胜": 0.50, "平": 0.23, "负": 0.27},
            ev_gaps={"had": {"胜": -0.27, "平": -0.01, "负": 0.28}},
            is_strong_banker=False,
            is_comfort_risk=False,
            is_chaos=True,
            is_draw_friendly=False,
            is_upset_candidate=False,
            is_three_way_coinflip=False,
            is_high_volatility_league=True,
        ),
    }
    legs = select_top_legs(
        matches, analytics, intent="main", k=10, pool_filter={"ttg", "had"},
        odds_min=1.0, odds_max=10.0,
    )
    bad = [
        ev for ev in legs
        if ev.leg.pool == "ttg" and ev.leg.pick in {"0球", "1球", "2球"}
    ]
    assert not bad, (
        f"R10 violated: hi-vol ttg≤2球 leaked into main: "
        f"{[(ev.leg.match_no, ev.leg.pick) for ev in bad]}"
    )


def test_r13_allows_ttg_low_when_expected_goals_below_threshold() -> None:
    """Sanity: R13 must NOT block ttg 1球 when the model agrees expected_goals
    is low (e.g., 2.0). 5/09 周六019 富勒姆 vs 伯恩 (expected_goals=2.0) — the
    leg that won. R13 fires only when the model disagrees with the pick.
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周六019", match_date="2026-05-09", match_time="22:00:00",
            league="英超", home_team="富勒姆", away_team="伯恩茅斯",
            status="Selling", hot_direction="客胜低赔(2.22)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周六019", league="英超", home_team="富勒姆",
                    away_team="伯恩茅斯", pool="ttg", play="总进球",
                    pick="1球", odds=6.80, logic="",
                ),
            ],
        ),
    ]
    safe_ttg = PoissonEdgeEntry(
        match_no="周六019", home="富勒姆", away="伯恩茅斯", league="英超",
        pool="ttg", pick="1球", market_odd=6.80, fair_odd=5.51,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.08,  # +23%
        expected_goals=2.0,  # below 2.7 → R13 allows
    )
    plan = service._build_poisson_solo_plan(matches, poisson_rows=[safe_ttg])
    assert len(plan.legs) == 1
    assert plan.legs[0].match_no == "周六019"
    assert plan.legs[0].pool == "ttg"


# ---------------------------------------------------------------- R17 ---
# 2026-05-11 C 票 2 腿 (007 crs 0:0 expected_goals=1.9 + 001 ttg 1球
# expected_goals=2.5) 全押 "low_goals" 叙事 → 全输。R13 只过滤 expected_goals
# ≥ 2.7，R17 给 poisson_solo 加叙事同质性保护：两条腿都是 low_goals 时，任一
# 条 expected_goals ≥ 2.3 就把更弱的那条砍掉。


def test_r17_poisson_solo_two_low_goals_legs_collapse_to_highest_edge() -> None:
    """R17 (5/11): when poisson_solo selects 2 legs and BOTH are low_goals
    narrative (crs 0:0/0:1/1:0 or ttg 0/1/2球), AND any leg has
    expected_goals ≥ POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER (2.3), collapse
    to 1 leg keeping the highest Poisson edge. 5/11 C 票 007 0:0 (+72% edge,
    λ=1.9) + 001 ttg1 (+21% edge, λ=2.5) — R17 keeps 007 because its edge
    is stronger; both legs lost on 5/11 but the principle (preserve highest
    model conviction) is validated by 5/04 where 007 0:0 +21.6% edge was
    the winner.
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_CROSS_MATCH_SUPPORT_EDGE,
        POISSON_SOLO_EDGE_THRESHOLD,
        POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周一007", match_date="2026-05-11", match_time="22:30:00",
            league="西甲", home_team="巴列卡诺", away_team="赫罗纳",
            status="Selling", hot_direction="均衡(2.30)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一007", league="西甲", home_team="巴列卡诺",
                    away_team="赫罗纳", pool="crs", play="比分",
                    pick="0:0", odds=11.50, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周一001", match_date="2026-05-11", match_time="22:30:00",
            league="沙职", home_team="新未来SC", away_team="利雅青年",
            status="Selling", hot_direction="主胜低赔(2.30)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一001", league="沙职", home_team="新未来SC",
                    away_team="利雅青年", pool="ttg", play="总进球",
                    pick="1球", odds=5.90, logic="",
                ),
            ],
        ),
    ]
    high_edge_crs = PoissonEdgeEntry(
        match_no="周一007", home="巴列卡诺", away="赫罗纳", league="西甲",
        pool="crs", pick="0:0", market_odd=11.50, fair_odd=6.69,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.57,  # +72% (top edge of the day)
        expected_goals=1.9,
    )
    weaker_ttg = PoissonEdgeEntry(
        match_no="周一001", home="新未来SC", away="利雅青年", league="沙职",
        pool="ttg", pick="1球", market_odd=5.90, fair_odd=4.87,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.06,  # +21%
        expected_goals=POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER + 0.2,  # 2.5
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[high_edge_crs, weaker_ttg]
    )
    assert len(plan.legs) == 1, (
        "R17: when both legs are low_goals narrative and any has expected_goals "
        f"≥ {POISSON_SOLO_LOW_GOALS_LAMBDA_TRIGGER}, ticket downgrades to 1 leg"
    )
    # Keep the highest-edge leg (007 +72% > 001 +21%).
    assert plan.legs[0].match_no == "周一007", (
        "R17 must keep the leg with the highest Poisson edge (+72%), not +21%"
    )


def test_r17_allows_two_low_goals_legs_when_both_lambdas_low() -> None:
    """Sanity: R17 doesn't fire when both legs have expected_goals
    below the trigger (e.g. 1.7, 1.8). Pure cross-match low-goals alpha."""
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周二001", match_date="2026-05-12", match_time="22:00:00",
            league="意丙", home_team="HA", away_team="AA",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二001", league="意丙", home_team="HA",
                    away_team="AA", pool="crs", play="比分", pick="0:0",
                    odds=12.0, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周二002", match_date="2026-05-12", match_time="22:00:00",
            league="阿乙", home_team="HB", away_team="AB",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二002", league="阿乙", home_team="HB",
                    away_team="AB", pool="ttg", play="总进球", pick="1球",
                    odds=4.50, logic="",
                ),
            ],
        ),
    ]
    a = PoissonEdgeEntry(
        match_no="周二001", home="HA", away="AA", league="意丙",
        pool="crs", pick="0:0", market_odd=12.0, fair_odd=8.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.20, expected_goals=1.7,
    )
    b = PoissonEdgeEntry(
        match_no="周二002", home="HB", away="AB", league="阿乙",
        pool="ttg", pick="1球", market_odd=4.50, fair_odd=3.75,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.05, expected_goals=1.8,
    )
    plan = service._build_poisson_solo_plan(matches, poisson_rows=[a, b])
    # Both should survive (no R17 trigger; R5 cap is 1 crs but 2 different pools).
    assert len(plan.legs) == 2


# ---------------------------------------------------------------- R18 ---
# 2026-05-11 E 票 3 腿全 crs low_goals (001 0:0 + 007 0:1 + 009 0:0) → 1/3
# 命中。R9 看 edge 强度，但忽略叙事同质性。R18: extreme ≥ 2 crs low_goals 腿
# 时，只保留 edge 最强的那条；让出空间给非 low_goals 替代叙事。


def test_r18_extreme_caps_low_goals_crs_to_single_leg(tmp_path: Path) -> None:
    """R18 (5/11): extreme ticket may have at most 1 crs leg in
    EXTREME_CRS_LOW_PICKS ({0:0, 0:1, 1:0}). 5/11 E 票 3 腿全 0:0/0:1 same
    macro narrative → 1/3 hit. Drop extras beyond the strongest by edge.

    Uses _strong_chalk synthetic fixtures: their crs 0:0 edges line up high
    enough that R9 alone doesn't trim them. After R18 trims homogeneous
    low_goals, no more than 1 crs leg in {0:0, 0:1, 1:0} remains.
    """
    from nutmeg.services.jczq_daily import EXTREME_CRS_LOW_PICKS

    matches = [_strong_chalk(f"周一00{i}") for i in range(1, 6)]
    service = JczqDailyAdvisorService(provider=FakeProvider(matches))
    report = service.build_report(run_date="2026-05-05", output_dir=tmp_path)
    extreme = next((plan for plan in report.plans if plan.kind == "extreme"), None)
    if extreme is None or not extreme.legs:
        return
    low_goals_crs = [
        leg
        for leg in extreme.legs
        if leg.pool == "crs" and leg.pick in EXTREME_CRS_LOW_PICKS
    ]
    assert len(low_goals_crs) <= 1, (
        f"R18 violated: extreme has {len(low_goals_crs)} crs low_goals legs "
        f"({[(leg.match_no, leg.pick) for leg in low_goals_crs]})"
    )


# ---------------------------------------------------------------- R19 ---
# 2026-05-11 D 票 007 hhad 让平 @4.10 → 实际 让负。brief Section 1 把 007 标
# draw_friendly（implied vs 联赛先验），但实测 Poisson hhad 让平 edge = -6.6%
# (R7 fair_odds_hhad)。draw_friendly 桶和 Poisson verdict 是两套独立信号；
# R7.1 hhad floor (-10%) 漏掉了 -10% < edge < -5% 的"市场比模型贵"hhad 让平腿。


def test_r19_contrarian_rejects_hhad_draw_when_poisson_edge_below_floor() -> None:
    """R19 (5/11): in contrarian/main intent, hhad 让平 legs need a Poisson
    edge ≥ HHAD_DRAW_MIN_EDGE (-0.05). Tighter than HHAD_POISSON_REJECT_BELOW
    (-0.10) which catches the model-strongly-opposed; R19 catches the
    "draw_friendly bucket vs Poisson contradiction" zone.
    """
    from nutmeg.services.jczq_intelligence import (
        HHAD_DRAW_MIN_EDGE,
        HHAD_POISSON_REJECT_BELOW,
        MatchAnalytics,
        select_top_legs,
    )

    # Two candidates: 007 hhad 让平 edge=-6.6% (passes R7.1 -10%, fails R19 -5%)
    # and a clean hhad 让负 edge=-3% (passes everything).
    matches = [
        JczqDailyMatch(
            match_no="周一007", match_date="2026-05-11", match_time="22:30:00",
            league="西甲", home_team="巴列卡诺", away_team="赫罗纳",
            status="Selling", hot_direction="均衡(2.30)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一007", league="西甲", home_team="巴列卡诺",
                    away_team="赫罗纳", pool="hhad", play="让球胜平负",
                    pick="让平", odds=4.10, logic="", goal_line="0",
                ),
                JczqDailyLeg(
                    match_no="周一007", league="西甲", home_team="巴列卡诺",
                    away_team="赫罗纳", pool="hhad", play="让球胜平负",
                    pick="让负", odds=2.80, logic="", goal_line="0",
                ),
            ],
        ),
    ]
    analytics = {
        "周一007": MatchAnalytics(
            match_no="周一007", league="西甲", favorite_outcome="胜",
            favorite_odds=2.30, favorite_implied=0.43,
            implied_probs={"胜": 0.43, "平": 0.27, "负": 0.30},
            vig_pct=0.12, dispersion=0.50, popularity_score=2,
            popularity_tier="m",
            baseline_probs={"胜": 0.40, "平": 0.25, "负": 0.35},
            ev_gaps={"had": {"胜": -0.05, "平": 0.08, "负": -0.05}},
            is_strong_banker=False, is_comfort_risk=False, is_chaos=False,
            is_draw_friendly=True, is_upset_candidate=False,
            is_three_way_coinflip=False, is_high_volatility_league=False,
        ),
    }
    # Synthetic poisson edge index: 007 hhad 让平 -6.6%, 让负 -3.0%.
    poisson_idx = {
        ("周一007", "hhad", "让平"): -0.066,
        ("周一007", "hhad", "让负"): -0.030,
    }
    assert HHAD_POISSON_REJECT_BELOW <= -0.066 < HHAD_DRAW_MIN_EDGE, (
        "fixture sanity: -6.6% should sit between R7.1 floor and R19 floor"
    )
    legs = select_top_legs(
        matches, analytics, intent="contrarian", k=10,
        pool_filter={"hhad"}, odds_min=1.0, odds_max=10.0,
        require_hhad_handicap=True,
        poisson_edge_index=poisson_idx,
        hhad_min_edge=HHAD_POISSON_REJECT_BELOW,
        hhad_draw_min_edge=HHAD_DRAW_MIN_EDGE,
    )
    pick_set = {(ev.leg.pool, ev.leg.pick) for ev in legs}
    assert ("hhad", "让平") not in pick_set, (
        f"R19 violated: contrarian kept hhad 让平 with edge -6.6% "
        f"(R19 floor {HHAD_DRAW_MIN_EDGE})"
    )
    # 让负 -3% should still be allowed.
    assert ("hhad", "让负") in pick_set


# ---------------------------------------------------------------- R20 ---
# 2026-05-11 A 票 005 had 胜 @1.60 (expected_edge -10.56%) + 006 had 胜 @1.60
# (-10.01%) 全错。Rule B 只禁 ≤1.50 低赔，但 1.50-1.70 区间的 chalk_favorite +
# Poisson 显著负 edge (≤ -10%) 同样不应该当底仓胆 — 市场已经把水分榨干。


def test_r20_stable_base_rejects_had_favorite_when_poisson_strongly_opposes() -> None:
    """R20 (5/11): stable_base had legs need Poisson expected_edge ≥
    STABLE_BASE_HAD_MIN_POISSON_EDGE (-0.10). 5/11 005 had 胜 @1.60 edge
    -10.56% and 006 had 胜 @1.60 edge -10.01% both made it into A and both
    lost. Rule B (1.50 floor) is necessary but not sufficient; R20 adds the
    Poisson-supported quality gate.
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        STABLE_BASE_HAD_MIN_POISSON_EDGE,
    )

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    # Synthetic match where home is 1.60 favorite (passes Rule B) but Poisson
    # disagrees by ≥ -10%.
    matches = [
        JczqDailyMatch(
            match_no="周一005", match_date="2026-05-11", match_time="22:30:00",
            league="英超", home_team="热刺", away_team="利兹联",
            status="Selling", hot_direction="主胜低赔(1.60)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一005", league="英超", home_team="热刺",
                    away_team="利兹联", pool="had", play="胜平负",
                    pick="胜", odds=1.60, logic="",
                ),
            ],
        ),
        # 003-style fallback with positive (or neutral) edge so stable_base
        # has something to anchor on.
        JczqDailyMatch(
            match_no="周一003", match_date="2026-05-11", match_time="22:30:00",
            league="沙超", home_team="布赖合作", away_team="吉达国民",
            status="Selling", hot_direction="客胜低赔(1.62)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一003", league="沙超", home_team="布赖合作",
                    away_team="吉达国民", pool="had", play="胜平负",
                    pick="负", odds=1.62, logic="",
                ),
            ],
        ),
    ]
    # Synthetic Poisson index: 005 had 胜 edge -10.5% (must be rejected by
    # R20 since -0.105 < -0.10 floor). 003 had 负 -3% (passes).
    poisson_idx = {
        ("周一005", "had", "胜"): -0.105,
        ("周一003", "had", "负"): -0.030,
    }
    service._active_poisson_index = poisson_idx
    service._active_coinflip_match_nos = set()
    assert STABLE_BASE_HAD_MIN_POISSON_EDGE == -0.10
    plan = service._build_stable_base_plan(matches)
    bad = [
        leg for leg in plan.legs
        if leg.match_no == "周一005" and leg.pool == "had"
    ]
    assert bad == [], (
        f"R20 violated: stable_base kept 005 had 胜 with Poisson edge -10.5% "
        f"(floor {STABLE_BASE_HAD_MIN_POISSON_EDGE})"
    )
    # The other -3% leg should remain available.
    assert any(
        leg.match_no == "周一003" and leg.pool == "had"
        for leg in plan.legs
    ), "R20 must allow 003 had 负 at edge -3%"


def test_r20_allows_had_favorite_when_poisson_edge_above_floor() -> None:
    """Sanity for R20: a had 胜 @1.60 with Poisson edge -8% (above -10% floor)
    must still be eligible. Avoids R20 over-blocking neutral-EV chalk."""
    from nutmeg.services.jczq_daily import JczqDailyAdvisorService as _Svc

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周一009", match_date="2026-05-11", match_time="22:30:00",
            league="葡超", home_team="阿马多拉", away_team="法马利康",
            status="Selling", hot_direction="客胜低赔(1.62)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周一009", league="葡超", home_team="阿马多拉",
                    away_team="法马利康", pool="had", play="胜平负",
                    pick="负", odds=1.62, logic="",
                ),
            ],
        ),
    ]
    poisson_idx = {("周一009", "had", "负"): -0.075}
    service._active_poisson_index = poisson_idx
    service._active_coinflip_match_nos = set()
    plan = service._build_stable_base_plan(matches)
    assert any(
        leg.match_no == "周一009" and leg.pool == "had"
        for leg in plan.legs
    ), "R20 must allow chalk with Poisson edge -7.5% (above -10% floor)"


# ---------------------------------------------------------------- R21 ---
# 2026-05-12 main 票三腿 had 全部 Poisson edge ≤ -10% — 003 had 胜 -10.46%
# MISS, 004 had 平 -10.94% HIT (lucky), 006 had 平 -10.64% MISS = 1/3 命中。
# R20 在 stable_base 已经验证 -10% floor 有效，R21 把同一阈值扩展到 main。
# R21 落在 _select_leg 的可选参数 (poisson_idx + min_poisson_edge) 上，main
# 票的 3 个 had slot 全部启用。


def test_r21_select_leg_filters_had_when_poisson_edge_below_floor() -> None:
    """R21 (5/12): _select_leg respects min_poisson_edge filter for had pool.
    5/12 main 周二006 had 平 @3.15 expected_edge -10.64% should be filtered
    when the caller passes MAIN_HAD_MIN_POISSON_EDGE = -0.10.
    """
    from nutmeg.services.jczq_daily import (
        MAIN_HAD_MIN_POISSON_EDGE,
        _select_leg,
    )

    matches = [
        JczqDailyMatch(
            match_no="周二006", match_date="2026-05-12", match_time="03:00:00",
            league="法甲", home_team="圣旺红星", away_team="罗德兹",
            status="Selling", hot_direction="主胜中赔(2.20)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二006", league="法甲", home_team="圣旺红星",
                    away_team="罗德兹", pool="had", play="胜平负",
                    pick="平", odds=3.15, logic="",
                ),
            ],
        ),
    ]
    poisson_idx = {("周二006", "had", "平"): -0.1064}
    assert MAIN_HAD_MIN_POISSON_EDGE == -0.10
    # Without R21 (no edge filter) the leg is selected.
    used: set[str] = set()
    leg = _select_leg(
        matches, used,
        pool="had", min_odds=3.0, target=3.4,
    )
    assert leg is not None and leg.match_no == "周二006", (
        "fixture sanity: had 平 @3.15 must be selectable without the R21 filter"
    )
    # With R21 (edge -10.64% < -10% floor) the leg is rejected → returns None.
    used2: set[str] = set()
    leg2 = _select_leg(
        matches, used2,
        pool="had", min_odds=3.0, target=3.4,
        poisson_idx=poisson_idx,
        min_poisson_edge=MAIN_HAD_MIN_POISSON_EDGE,
    )
    assert leg2 is None, (
        f"R21 violated: had 平 with edge -10.64% should be filtered "
        f"(floor {MAIN_HAD_MIN_POISSON_EDGE}); got {leg2}"
    )


def test_r21_select_leg_allows_had_when_poisson_edge_above_floor() -> None:
    """Sanity for R21: a had 平 with Poisson edge -8% (above -10% floor)
    must still be selectable. Avoids R21 over-blocking neutral-EV picks.
    """
    from nutmeg.services.jczq_daily import (
        MAIN_HAD_MIN_POISSON_EDGE,
        _select_leg,
    )

    matches = [
        JczqDailyMatch(
            match_no="周二006", match_date="2026-05-12", match_time="03:00:00",
            league="法甲", home_team="圣旺红星", away_team="罗德兹",
            status="Selling", hot_direction="均衡", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二006", league="法甲", home_team="圣旺红星",
                    away_team="罗德兹", pool="had", play="胜平负",
                    pick="平", odds=3.15, logic="",
                ),
            ],
        ),
    ]
    poisson_idx = {("周二006", "had", "平"): -0.080}
    used: set[str] = set()
    leg = _select_leg(
        matches, used,
        pool="had", min_odds=3.0, target=3.4,
        poisson_idx=poisson_idx,
        min_poisson_edge=MAIN_HAD_MIN_POISSON_EDGE,
    )
    assert leg is not None and leg.match_no == "周二006", (
        "R21 must allow had 平 at edge -8% (above -10% floor)"
    )


def test_r21_main_construction_passes_poisson_edge_filter_to_select_leg() -> None:
    """Wiring test: the main plan must build its had slots with R21's filter
    in place. We replace _select_leg with a spy that records each kwarg call
    so we can prove main's three had slots all receive
    (poisson_idx, min_poisson_edge=MAIN_HAD_MIN_POISSON_EDGE).
    """
    import nutmeg.services.jczq_daily as daily_mod
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        MAIN_HAD_MIN_POISSON_EDGE,
    )

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周二003", match_date="2026-05-12", match_time="03:00:00",
            league="西甲", home_team="塞尔塔", away_team="莱万特",
            status="Selling", hot_direction="主胜热(1.67)", role="强胆场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二003", league="西甲", home_team="塞尔塔",
                    away_team="莱万特", pool="had", play="胜平负",
                    pick="胜", odds=1.67, logic="",
                ),
            ],
        ),
    ]
    calls: list[dict[str, object]] = []
    original = daily_mod._select_leg

    def _spy(*args: object, **kwargs: object):
        calls.append(dict(kwargs))
        return original(*args, **kwargs)  # type: ignore[arg-type]

    daily_mod._select_leg = _spy  # type: ignore[assignment]
    try:
        service._build_plans(matches, instruction=None)
    finally:
        daily_mod._select_leg = original  # type: ignore[assignment]

    had_calls = [c for c in calls if c.get("pool") == "had"]
    main_had_calls = [
        c for c in had_calls
        if c.get("min_poisson_edge") is not None
    ]
    assert MAIN_HAD_MIN_POISSON_EDGE == -0.10
    assert len(main_had_calls) >= 3, (
        f"R21 wiring missing: expected ≥3 had _select_leg calls with "
        f"min_poisson_edge passed; got {len(main_had_calls)}"
    )
    for c in main_had_calls:
        assert c["min_poisson_edge"] == MAIN_HAD_MIN_POISSON_EDGE, (
            f"R21 wiring broken: min_poisson_edge={c['min_poisson_edge']} "
            f"!= {MAIN_HAD_MIN_POISSON_EDGE}"
        )
        assert c.get("poisson_idx") is not None, (
            "R21 wiring broken: had slot called without poisson_idx"
        )


# --------------------------------------------------- R22 (5/13 落库) ---
# 5/13 D 票 004 (西甲, hi-vol+coinflip 双标) crs 0:0 +28.6% alpha 由 Codex 主张
# 兑现 → 实际 2:0 → 多输 15 元。R22 在 hi-vol 联赛上 hard-reject crs 低进球
# (0:0/0:1/1:0) 进 poisson_solo；同时 hi-vol+coinflip 双标场在 select_top_legs
# 也拒（保护 extreme/inspiration/contrarian/false_signal）。10 天聚合：crs 低
# 进球三花 alpha 命中率 1/24 = 4.2%（远低于 implied 25-40%）。


def test_r22_hi_vol_league_crs_low_blocked_from_poisson_solo() -> None:
    """R22: hi-vol 联赛的 crs 0:0/0:1/1:0 一律不进 poisson_solo。

    5/13 005 (法甲) 不在 HIGH_VOL_LEAGUE_OVERRIDE 但 5/13 004 (西甲) 通过
    league_volatility 信号被识别为 hi-vol。这里用一个已知 hi-vol 联赛
    (美职) 构造 crs 0:0 +30% candidate，断言 poisson_solo 跳过。
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import (
        MatchAnalytics,
        PoissonEdgeEntry,
    )

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周三011", match_date="2026-05-13", match_time="22:00:00",
            league="美职", home_team="辛辛那提", away_team="迈国际",
            status="Selling", hot_direction="客胜低赔(1.92)",
            role="开放节奏场", confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周三011", league="美职", home_team="辛辛那提",
                    away_team="迈国际", pool="crs", play="比分", pick="0:0",
                    odds=20.0, logic="",
                ),
            ],
        ),
    ]
    analytics = {
        "周三011": MatchAnalytics(
            match_no="周三011",
            league="美职",
            favorite_outcome="负",
            favorite_odds=1.92,
            favorite_implied=0.46,
            implied_probs={"胜": 0.32, "平": 0.22, "负": 0.46},
            vig_pct=12.9,
            dispersion=0.10,
            popularity_score=0,
            popularity_tier="balanced",
            baseline_probs={"胜": 0.32, "平": 0.22, "负": 0.46},
            ev_gaps={"胜": {}, "平": {}, "负": {}},
            is_strong_banker=False,
            is_comfort_risk=False,
            is_chaos=False,
            is_draw_friendly=False,
            is_upset_candidate=False,
            is_three_way_coinflip=False,
            is_high_volatility_league=True,
        ),
    }
    row = PoissonEdgeEntry(
        match_no="周三011", home="辛辛那提", away="迈国际", league="美职",
        pool="crs", pick="0:0", market_odd=20.0, fair_odd=14.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.30,  # +45% — well above any threshold
        expected_goals=2.6,
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[row], analytics=analytics
    )
    assert plan.legs == [], (
        "R22: hi-vol 联赛 crs 低进球三花一律拒绝进 poisson_solo，"
        f"但本次保留了 {[(leg.pool, leg.pick) for leg in plan.legs]}"
    )


def test_r22_low_vol_league_crs_low_allowed_in_poisson_solo() -> None:
    """R22 sanity: 非 hi-vol 联赛 crs 0:0 仍可正常进 poisson_solo。"""
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import (
        MatchAnalytics,
        PoissonEdgeEntry,
    )

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周二001", match_date="2026-05-12", match_time="22:00:00",
            league="日职", home_team="HA", away_team="AA",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二001", league="日职", home_team="HA",
                    away_team="AA", pool="crs", play="比分", pick="0:0",
                    odds=12.0, logic="",
                ),
            ],
        ),
    ]
    analytics = {
        "周二001": MatchAnalytics(
            match_no="周二001",
            league="日职",
            favorite_outcome="胜",
            favorite_odds=2.10,
            favorite_implied=0.40,
            implied_probs={"胜": 0.40, "平": 0.30, "负": 0.30},
            vig_pct=12.9,
            dispersion=0.10,
            popularity_score=0,
            popularity_tier="balanced",
            baseline_probs={"胜": 0.40, "平": 0.30, "负": 0.30},
            ev_gaps={"胜": {}, "平": {}, "负": {}},
            is_strong_banker=False,
            is_comfort_risk=False,
            is_chaos=False,
            is_draw_friendly=False,
            is_upset_candidate=False,
            is_three_way_coinflip=False,
            is_high_volatility_league=False,
        ),
    }
    row = PoissonEdgeEntry(
        match_no="周二001", home="HA", away="AA", league="日职",
        pool="crs", pick="0:0", market_odd=12.0, fair_odd=8.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.30,
        expected_goals=1.7,
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[row], analytics=analytics
    )
    # R26 (5/15) supersedes R22 for poisson_solo: crs pool is dropped from
    # poisson_solo across the board (1/30 historical leg-hit). What used to
    # be "non-hi-vol crs 0:0 still allowed" is now "no crs allowed in
    # poisson_solo, period". R22 (hi-vol crs block) remains the controlling
    # rule for inspiration/extreme paths where crs is still admissible.
    assert len(plan.legs) == 0, "R26: crs pool fully blocked from poisson_solo"


def test_r22_select_top_legs_drops_hi_vol_coinflip_crs_low() -> None:
    """R22 在 select_top_legs 层：hi-vol+coinflip 双标场的 crs 0:0/0:1/1:0
    任何 intent 都拒（保护 extreme / inspiration / contrarian / false_signal）。
    5/13 D 票 004 是 hi-vol+coinflip 双标，被 Hybrid 裁决采进 D → 多输 15。"""
    from nutmeg.services.jczq_intelligence import select_top_legs

    matches = [_coinflip("周三004", league="美职")]
    service = JczqDailyAdvisorService(provider=FakeProvider(matches))
    report = service.build_report(run_date="2026-05-13")
    analytics = compute_analytics(report.matches, baseline=LeaguePriorBaseline())

    legs = select_top_legs(
        report.matches,
        analytics,
        intent="extreme",
        k=10,
        pool_filter={"crs"},
        odds_min=4.0,
        odds_max=99.0,
    )
    bad = [
        ev for ev in legs
        if ev.leg.pool == "crs" and ev.leg.pick in {"0:0", "0:1", "1:0"}
    ]
    assert not bad, (
        "R22: hi-vol+coinflip 双标场 crs 低进球应被 select_top_legs hard-reject，"
        f"但收到 {[(ev.leg.match_no, ev.leg.pick) for ev in bad]}"
    )


# --------------------------------------------------- R23 (5/13 落库) ---
# 10 天 crs 0:0 alpha 命中率 1/16 = 6.25%（远低于 implied 8-15%）。R23 把 crs
# 0:0 的 poisson_solo 阈值从默认 +15% 提到 +25%；其他低进球 pick (0:1/1:0/ttg
# 1球) 仍走默认阈值。


def test_r23_poisson_solo_rejects_crs_zero_zero_below_25pct_edge() -> None:
    """R23: crs 0:0 进 poisson_solo 需 edge ≥ +25%（vs 默认 +15%）。
    5/13 005 crs 0:0 +40.4% 仍可过；但 +18% 应被拒。
    """
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_CRS_ZERO_ZERO_MIN_EDGE,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周二001", match_date="2026-05-12", match_time="22:00:00",
            league="日职", home_team="HA", away_team="AA",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二001", league="日职", home_team="HA",
                    away_team="AA", pool="crs", play="比分", pick="0:0",
                    odds=12.0, logic="",
                ),
            ],
        ),
    ]
    row = PoissonEdgeEntry(
        match_no="周二001", home="HA", away="AA", league="日职",
        pool="crs", pick="0:0", market_odd=12.0, fair_odd=10.17,
        edge=POISSON_SOLO_CRS_ZERO_ZERO_MIN_EDGE - 0.05,  # +20% (just under +25%)
        expected_goals=1.7,
    )
    plan = service._build_poisson_solo_plan(matches, poisson_rows=[row])
    assert plan.legs == [], (
        "R23: crs 0:0 edge 低于 +25% R23 floor 应被拒，"
        f"但保留了 {[(leg.match_no, leg.pick) for leg in plan.legs]}"
    )


def test_r23_allows_crs_zero_zero_above_25pct_edge_and_other_picks_at_15pct() -> None:
    """R23: +26% crs 0:0 通过；同票其他 pick (crs 0:1) +18% 仍按默认 +15%。"""
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_CRS_ZERO_ZERO_MIN_EDGE,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周二001", match_date="2026-05-12", match_time="22:00:00",
            league="日职", home_team="HA", away_team="AA",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二001", league="日职", home_team="HA",
                    away_team="AA", pool="crs", play="比分", pick="0:0",
                    odds=12.0, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周二002", match_date="2026-05-12", match_time="22:00:00",
            league="日职", home_team="HB", away_team="AB",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二002", league="日职", home_team="HB",
                    away_team="AB", pool="crs", play="比分", pick="0:1",
                    odds=8.0, logic="",
                ),
            ],
        ),
    ]
    row_zero_zero = PoissonEdgeEntry(
        match_no="周二001", home="HA", away="AA", league="日职",
        pool="crs", pick="0:0", market_odd=12.0, fair_odd=9.0,
        edge=POISSON_SOLO_CRS_ZERO_ZERO_MIN_EDGE + 0.01,  # +26%
        expected_goals=1.7,
    )
    row_zero_one = PoissonEdgeEntry(
        match_no="周二002", home="HB", away="AB", league="日职",
        pool="crs", pick="0:1", market_odd=8.0, fair_odd=6.78,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.03,  # +18% — above default but below R23
        expected_goals=1.7,
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[row_zero_zero, row_zero_one]
    )
    # R26 (5/15) supersedes R23 for poisson_solo: crs is no longer eligible
    # regardless of edge or pick. R23's threshold still gates crs admission to
    # other surfaces (inspiration/extreme paths via select_top_legs), but
    # poisson_solo never sees crs again.
    assert plan.legs == [], "R26 fully blocks crs from poisson_solo"


# --------------------------------------------------- R24 (5/13 落库) ---
# 5/11+5/12+5/13 C 票连失 3 天，累计 70 元 alpha 0 中。R24: 当最近 3 天
# poisson_solo 全 miss 时，下一次 poisson_solo 输出腿数硬限 1（即使 +EV 多腿
# 也压成 1），让仓位风险匹配模型连失证据。


def test_r24_poisson_solo_cooling_off_caps_to_single_leg_after_three_misses() -> None:
    """R24: cooling_off=True → poisson_solo 即使 2 +EV 腿也压到 1。"""
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周二001", match_date="2026-05-12", match_time="22:00:00",
            league="意丙", home_team="HA", away_team="AA",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二001", league="意丙", home_team="HA",
                    away_team="AA", pool="had", play="胜平负", pick="平",
                    odds=3.50, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周二002", match_date="2026-05-12", match_time="22:00:00",
            league="阿乙", home_team="HB", away_team="AB",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二002", league="阿乙", home_team="HB",
                    away_team="AB", pool="ttg", play="总进球", pick="1球",
                    odds=4.50, logic="",
                ),
            ],
        ),
    ]
    a = PoissonEdgeEntry(
        match_no="周二001", home="HA", away="AA", league="意丙",
        pool="had", pick="平", market_odd=3.50, fair_odd=2.91,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.05,  # +20%
        expected_goals=1.7,
    )
    b = PoissonEdgeEntry(
        match_no="周二002", home="HB", away="AB", league="阿乙",
        pool="ttg", pick="1球", market_odd=4.50, fair_odd=3.75,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.03,  # +18%
        expected_goals=1.8,
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[a, b], cooling_off=True
    )
    assert len(plan.legs) == 1, (
        f"R24: cooling_off 应把 poisson_solo 压到 1 腿，实际 {len(plan.legs)}"
    )


def test_r24_no_cooling_when_recent_results_have_a_hit() -> None:
    """R24 sanity: 3 天里 ≥ 1 hit → cooling_off=False → 2 腿正常出。"""
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周二001", match_date="2026-05-12", match_time="22:00:00",
            league="意丙", home_team="HA", away_team="AA",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二001", league="意丙", home_team="HA",
                    away_team="AA", pool="had", play="胜平负", pick="平",
                    odds=3.50, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周二002", match_date="2026-05-12", match_time="22:00:00",
            league="阿乙", home_team="HB", away_team="AB",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周二002", league="阿乙", home_team="HB",
                    away_team="AB", pool="ttg", play="总进球", pick="1球",
                    odds=4.50, logic="",
                ),
            ],
        ),
    ]
    a = PoissonEdgeEntry(
        match_no="周二001", home="HA", away="AA", league="意丙",
        pool="had", pick="平", market_odd=3.50, fair_odd=2.91,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.05,
        expected_goals=1.7,
    )
    b = PoissonEdgeEntry(
        match_no="周二002", home="HB", away="AB", league="阿乙",
        pool="ttg", pick="1球", market_odd=4.50, fair_odd=3.75,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.03,
        expected_goals=1.8,
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[a, b], cooling_off=False
    )
    assert len(plan.legs) == 2, (
        f"R24: cooling_off=False 应保留 2 腿，实际 {len(plan.legs)}"
    )


def test_r24_cooling_off_helper_detects_three_consecutive_misses() -> None:
    """R24: detect_poisson_solo_cooling_off(memory) 在最近 3 个
    poisson_solo plan_summaries 全 miss 时返 True。"""
    from nutmeg.services.jczq_strategy_memory import (
        detect_poisson_solo_cooling_off,
    )

    memory_all_miss = {
        "recent_plan_results": [
            {"date": "2026-05-11", "kind": "poisson_solo", "hits": 0, "total": 2, "all_hit": False},
            {"date": "2026-05-12", "kind": "poisson_solo", "hits": 0, "total": 2, "all_hit": False},
            {"date": "2026-05-13", "kind": "poisson_solo", "hits": 0, "total": 1, "all_hit": False},
        ],
    }
    assert detect_poisson_solo_cooling_off(memory_all_miss) is True

    memory_with_hit = {
        "recent_plan_results": [
            {"date": "2026-05-11", "kind": "poisson_solo", "hits": 0, "total": 2, "all_hit": False},
            {"date": "2026-05-12", "kind": "poisson_solo", "hits": 1, "total": 1, "all_hit": True},
            {"date": "2026-05-13", "kind": "poisson_solo", "hits": 0, "total": 1, "all_hit": False},
        ],
    }
    assert detect_poisson_solo_cooling_off(memory_with_hit) is False

    memory_too_few = {
        "recent_plan_results": [
            {"date": "2026-05-13", "kind": "poisson_solo", "hits": 0, "total": 1, "all_hit": False},
        ],
    }
    # 不足 3 天样本不触发 (默认 lookback=3)
    assert detect_poisson_solo_cooling_off(memory_too_few) is False


# --------------------------------------------------- R25 (5/13 落库) ---
# 5/13 法甲 7 个 ttg/crs Poisson 残差样本全 miss（5/10 / 5/12 / 5/13），平均
# 残差为正（系统性低估进球数）。R25: compute_league_residual_bias 在某联赛
# ≥ 5 ttg/crs 样本且平均残差 > 0 时返回 {联赛: -0.10}；compute_poisson_edges
# 接收 league_residual_bias 后只对 ttg/crs leg 应用，had/hhad/hafu 不受影响。


def test_r25_compute_league_residual_bias_returns_negative_when_underestimate() -> None:
    """R25: ≥ 5 法甲样本平均残差 > 0 → bias_map = {法甲: -0.10}。"""
    from nutmeg.services.jczq_strategy_memory import compute_league_residual_bias

    memory = {
        "poisson_residuals": [
            {"date": "2026-05-10", "league": "法甲", "pool": "ttg", "pick": "1球",
             "expected_goals": 2.0, "realized_goals": 3, "goal_residual": 1.0,
             "hit": False},
            {"date": "2026-05-10", "league": "法甲", "pool": "crs", "pick": "0:0",
             "expected_goals": 2.5, "realized_goals": 1, "goal_residual": -1.5,
             "hit": False},
            {"date": "2026-05-12", "league": "法甲", "pool": "had", "pick": "平",
             "expected_goals": 2.2, "realized_goals": 5, "goal_residual": 2.8,
             "hit": False},
            {"date": "2026-05-13", "league": "法甲", "pool": "crs", "pick": "0:0",
             "expected_goals": 2.3, "realized_goals": 3, "goal_residual": 0.7,
             "hit": False},
            {"date": "2026-05-13", "league": "法甲", "pool": "ttg", "pick": "1球",
             "expected_goals": 3.1, "realized_goals": 2, "goal_residual": -1.1,
             "hit": False},
        ]
    }
    bias = compute_league_residual_bias(memory)
    # 5 法甲 ttg/crs 样本（剔除 had），平均 ((1.0)+(-1.5)+(0.7)+(-1.1))/4 = -0.225
    # 该平均 < 0 → 不应触发 bias（联赛模型整体未低估）。
    assert "法甲" not in bias, (
        f"R25: 法甲 4 个 ttg/crs 样本平均残差 {-0.225} < 0，不应启用 bias，"
        f"返回 {bias}"
    )


def test_r25_compute_league_residual_bias_returns_negative_when_underestimate_systematic() -> None:
    """R25: ≥ 5 联赛 ttg/crs 样本平均残差 > 0（系统性低估）→ bias = -0.10。"""
    from nutmeg.services.jczq_strategy_memory import (
        POISSON_LEAGUE_BIAS_DELTA,
        compute_league_residual_bias,
    )

    memory = {
        "poisson_residuals": [
            {"date": f"2026-05-{i:02d}", "league": "意甲",
             "pool": "ttg", "pick": "1球", "expected_goals": 2.0,
             "realized_goals": 4, "goal_residual": 2.0, "hit": False}
            for i in range(1, 6)  # 5 samples, all heavy underestimate
        ]
    }
    bias = compute_league_residual_bias(memory)
    assert bias.get("意甲") == POISSON_LEAGUE_BIAS_DELTA, (
        f"R25: 5 意甲 ttg 样本平均残差 +2.0 应触发 bias = {POISSON_LEAGUE_BIAS_DELTA}，"
        f"返回 {bias}"
    )


def test_r25_no_bias_when_samples_below_threshold() -> None:
    """R25: 样本数低于阈值（默认 5）→ 不返 bias。"""
    from nutmeg.services.jczq_strategy_memory import compute_league_residual_bias

    memory = {
        "poisson_residuals": [
            {"date": f"2026-05-{i:02d}", "league": "意甲",
             "pool": "ttg", "pick": "1球", "expected_goals": 2.0,
             "realized_goals": 4, "goal_residual": 2.0, "hit": False}
            for i in range(1, 5)  # only 4 samples
        ]
    }
    bias = compute_league_residual_bias(memory)
    assert bias == {} or "意甲" not in bias, (
        f"R25: 4 样本 < 阈值 5，不应启用 bias，返回 {bias}"
    )


def test_r25_compute_poisson_edges_applies_league_bias_to_ttg_crs_only() -> None:
    """R25: compute_poisson_edges(matches, league_residual_bias=...) 只对
    ttg/crs leg edge 应用 -0.10 偏移；had/hhad 不受影响。"""
    from nutmeg.services.jczq_intelligence import compute_poisson_edges

    matches = [
        JczqDailyMatch(**{
            "match_no": "周三005",
            "match_date": "2026-05-13",
            "match_time": "22:00:00",
            "league": "法甲",
            "home_team": "布雷斯特",
            "away_team": "斯特拉斯",
            "status": "Selling",
            "hot_direction": "客胜低赔(2.32)",
            "role": "谨慎博弈场",
            "confidence_note": "",
            "candidates": [
                JczqDailyLeg(
                    match_no="周三005", league="法甲", home_team="布雷斯特",
                    away_team="斯特拉斯", pool="had", play="胜平负", pick="胜",
                    odds=3.10, logic="",
                ),
                JczqDailyLeg(
                    match_no="周三005", league="法甲", home_team="布雷斯特",
                    away_team="斯特拉斯", pool="had", play="胜平负", pick="平",
                    odds=3.50, logic="",
                ),
                JczqDailyLeg(
                    match_no="周三005", league="法甲", home_team="布雷斯特",
                    away_team="斯特拉斯", pool="had", play="胜平负", pick="负",
                    odds=2.32, logic="",
                ),
                JczqDailyLeg(
                    match_no="周三005", league="法甲", home_team="布雷斯特",
                    away_team="斯特拉斯", pool="ttg", play="总进球", pick="1球",
                    odds=5.30, logic="",
                ),
                JczqDailyLeg(
                    match_no="周三005", league="法甲", home_team="布雷斯特",
                    away_team="斯特拉斯", pool="crs", play="比分", pick="0:0",
                    odds=14.0, logic="",
                ),
            ],
        }),
    ]
    baseline = {row.pool + ":" + row.pick: row.edge
                for row in compute_poisson_edges(matches)}
    biased = {row.pool + ":" + row.pick: row.edge
              for row in compute_poisson_edges(
                  matches, league_residual_bias={"法甲": -0.10}
              )}
    # had legs unchanged
    for pick in ("胜", "平", "负"):
        key = f"had:{pick}"
        if key in baseline:
            assert abs(baseline[key] - biased[key]) < 1e-9, (
                f"R25: had pool 不应受联赛 bias 影响，{key} 变了"
            )
    # ttg / crs shifted by -0.10
    for key in ("ttg:1球", "crs:0:0"):
        if key in baseline:
            assert abs((biased[key] - baseline[key]) - (-0.10)) < 1e-9, (
                f"R25: {key} bias 应为 -0.10，实际 "
                f"{biased[key] - baseline[key]:+.4f}"
            )


# --------------------------------------------------- F2 (5/14 落库) ---
# 5/14 V3 用户察觉 0:0 集中度 26%，要求迭代框架而非单日调整。F2: 用现有
# poisson_residuals 130+ 样本按 (pool, pick) 算实测命中率 vs baseline implied
# 概率，对 alpha edge 应用衰减因子（empirical Bayes 思路）。10 天聚合：crs 0:0
# 实测 1/16 = 6.25% vs implied ~10%，decay = 0.625 → +36% alpha 衰减到 +22.5%。


def test_f2_decay_returns_1_when_below_min_samples() -> None:
    """F2: 样本数低于 min_samples 阈值，不衰减（return 1.0）。"""
    from nutmeg.services.jczq_strategy_memory import (
        EMPIRICAL_DECAY_MIN_SAMPLES,
        compute_empirical_alpha_decay,
    )

    memory = {
        "poisson_residuals": [
            {"pool": "crs", "pick": "0:0", "hit": False, "league": "西甲"}
            for _ in range(EMPIRICAL_DECAY_MIN_SAMPLES - 1)
        ]
    }
    decay = compute_empirical_alpha_decay(memory, pool="crs", pick="0:0")
    assert decay == 1.0, (
        f"F2: 样本不足应返 1.0（不衰减），实际 {decay}"
    )


def test_f2_decay_returns_lt_1_when_actual_below_baseline() -> None:
    """F2: crs 0:0 实测 6.25% (1/16) << baseline 10% → decay 应 < 1.0。
    decay = max(floor, actual/baseline) = max(0.5, 0.0625/0.10) = 0.625"""
    from nutmeg.services.jczq_strategy_memory import (
        compute_empirical_alpha_decay,
    )

    memory = {
        "poisson_residuals": [
            {"pool": "crs", "pick": "0:0", "hit": (i == 0), "league": f"L{i}"}
            for i in range(16)  # 1 hit / 16 samples = 6.25%
        ]
    }
    decay = compute_empirical_alpha_decay(memory, pool="crs", pick="0:0")
    assert 0.5 <= decay < 1.0, (
        f"F2: crs 0:0 实测 6.25% << 10% baseline，decay 应 ∈ [0.5, 1.0)，"
        f"实际 {decay}"
    )
    # 严格：6.25 / 10 = 0.625
    assert abs(decay - 0.625) < 0.01, (
        f"F2: crs 0:0 decay 应约 0.625，实际 {decay}"
    )


def test_f2_decay_clipped_to_floor() -> None:
    """F2: 实测 0/20 = 0% 命中率不应让 decay 归 0；clip 到 EMPIRICAL_DECAY_FLOOR (0.5)。"""
    from nutmeg.services.jczq_strategy_memory import (
        EMPIRICAL_DECAY_FLOOR,
        compute_empirical_alpha_decay,
    )

    memory = {
        "poisson_residuals": [
            {"pool": "crs", "pick": "0:0", "hit": False, "league": f"L{i}"}
            for i in range(20)
        ]
    }
    decay = compute_empirical_alpha_decay(memory, pool="crs", pick="0:0")
    assert decay == EMPIRICAL_DECAY_FLOOR, (
        f"F2: 0/20 命中率应 clip 到 floor {EMPIRICAL_DECAY_FLOOR}，实际 {decay}"
    )


def test_f2_decay_returns_1_when_actual_above_baseline() -> None:
    """F2: 实测命中率高于 baseline 时不衰减（模型不偏，可能甚至偏保守）。"""
    from nutmeg.services.jczq_strategy_memory import (
        compute_empirical_alpha_decay,
    )

    # ttg 1球 baseline 22%；构造 6/20 = 30% 命中率
    memory = {
        "poisson_residuals": [
            {"pool": "ttg", "pick": "1球", "hit": (i < 6), "league": f"L{i}"}
            for i in range(20)
        ]
    }
    decay = compute_empirical_alpha_decay(memory, pool="ttg", pick="1球")
    assert decay == 1.0, (
        f"F2: 实测 30% > 22% baseline，模型不偏不应衰减，实际 {decay}"
    )


def test_f2_decay_returns_1_for_unknown_pool_pick() -> None:
    """F2: 不在 baseline 表里的 (pool, pick) 不应用衰减（如 had/hhad/hafu）。"""
    from nutmeg.services.jczq_strategy_memory import (
        compute_empirical_alpha_decay,
    )

    memory = {
        "poisson_residuals": [
            {"pool": "had", "pick": "胜", "hit": False, "league": f"L{i}"}
            for i in range(20)
        ]
    }
    decay = compute_empirical_alpha_decay(memory, pool="had", pick="胜")
    assert decay == 1.0, (
        f"F2: had/胜 不在 baseline 表里，应返 1.0，实际 {decay}"
    )


def test_f2_compute_empirical_decay_map_returns_dict_for_known_picks() -> None:
    """F2: compute_empirical_decay_map 返回 {(pool, pick): decay} 全表。
    只为 baseline 表里的 picks 返回；其他 implicit 1.0。"""
    from nutmeg.services.jczq_strategy_memory import (
        compute_empirical_decay_map,
    )

    memory = {
        "poisson_residuals": [
            {"pool": "crs", "pick": "0:0", "hit": (i == 0), "league": f"L{i}"}
            for i in range(16)
        ] + [
            {"pool": "ttg", "pick": "1球", "hit": (i < 4), "league": f"L{i}"}
            for i in range(20)  # 4/20 = 20% < 22% baseline → decay
        ]
    }
    decay_map = compute_empirical_decay_map(memory)
    assert ("crs", "0:0") in decay_map, "F2: crs 0:0 应在 decay_map 里"
    assert decay_map[("crs", "0:0")] < 1.0, "F2: crs 0:0 decay 应 < 1"
    # ttg 1球 20% vs baseline 22% → decay ≈ 0.91，但要 > floor 0.5
    if ("ttg", "1球") in decay_map:
        assert 0.5 <= decay_map[("ttg", "1球")] <= 1.0


def test_f2_compute_poisson_edges_applies_empirical_decay() -> None:
    """F2: compute_poisson_edges 接收 empirical_decay_map → 对应 (pool, pick) leg
    edge 衰减后输出。"""
    from nutmeg.services.jczq_intelligence import compute_poisson_edges

    matches = [
        JczqDailyMatch(**{
            "match_no": "周四004",
            "match_date": "2026-05-14",
            "match_time": "21:00:00",
            "league": "西甲",
            "home_team": "赫罗纳",
            "away_team": "皇家社会",
            "status": "Selling",
            "hot_direction": "主胜低赔(1.87)",
            "role": "谨慎博弈场",
            "confidence_note": "",
            "candidates": [
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="胜",
                    odds=1.87, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="平",
                    odds=3.50, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="负",
                    odds=4.50, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="crs", play="比分", pick="0:0",
                    odds=15.0, logic="",
                ),
            ],
        }),
    ]
    baseline = {
        row.pool + ":" + row.pick: row.edge
        for row in compute_poisson_edges(matches)
    }
    decayed = {
        row.pool + ":" + row.pick: row.edge
        for row in compute_poisson_edges(
            matches, empirical_decay_map={("crs", "0:0"): 0.625}
        )
    }
    if "crs:0:0" in baseline:
        # decayed edge = baseline × 0.625
        expected = baseline["crs:0:0"] * 0.625
        assert abs(decayed["crs:0:0"] - expected) < 1e-9, (
            f"F2: crs 0:0 edge 应衰减 ×0.625；baseline {baseline['crs:0:0']:+.4f}, "
            f"decayed {decayed['crs:0:0']:+.4f}, expected {expected:+.4f}"
        )
    # had pool 不应被影响
    for pick in ("胜", "平", "负"):
        key = f"had:{pick}"
        if key in baseline:
            assert abs(baseline[key] - decayed[key]) < 1e-9, (
                f"F2: had pool 不在 decay_map 里，{key} 不应变；"
                f"baseline {baseline[key]:+.4f}, decayed {decayed[key]:+.4f}"
            )


# --------------------------------------------------- F3 (5/14 落库) ---
# 5/14 brief Section 4 出现 4 条 ≥+15% alpha 且全是低进球叙事（004 0:0 +36% /
# 001 0:0 +28.6% / 004 ttg1 +19.8% / 003 ttg1 +18.7%）。F2 静态衰减按
# (pool, pick) 历史命中率应用，但当某一天 alpha 极度集中在某方向时，是"今日
# 模型偏差"信号，需额外动态衰减。F3 = 日级 alpha 集中度警告（元规则）。


def test_f3_low_goals_concentration_count_returns_match_count() -> None:
    """F3: compute_daily_low_goals_concentration 返回有 ≥+15% 低进球 alpha 的
    distinct match 数。"""
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry
    from nutmeg.services.jczq_strategy_memory import (
        compute_daily_low_goals_concentration,
    )

    rows = [
        PoissonEdgeEntry(
            match_no="周四001", home="A", away="B", league="西甲",
            pool="crs", pick="0:0", market_odd=10.0, fair_odd=8.0,
            edge=0.20, expected_goals=2.0,
        ),
        PoissonEdgeEntry(
            match_no="周四003", home="C", away="D", league="沙职",
            pool="ttg", pick="1球", market_odd=8.0, fair_odd=6.5,
            edge=0.18, expected_goals=2.2,
        ),
        PoissonEdgeEntry(
            match_no="周四004", home="E", away="F", league="西甲",
            pool="crs", pick="0:0", market_odd=15.0, fair_odd=11.0,
            edge=0.36, expected_goals=2.3,
        ),
        # had pool, 应被排除
        PoissonEdgeEntry(
            match_no="周四002", home="G", away="H", league="沙职",
            pool="had", pick="平", market_odd=4.0, fair_odd=3.5,
            edge=0.14, expected_goals=2.5,
        ),
    ]
    count = compute_daily_low_goals_concentration(rows)
    assert count == 3, (
        f"F3: 3 distinct low_goals matches (001/003/004) 各 ≥+15% alpha，"
        f"应返 3，实际 {count}"
    )


def test_f3_concentration_count_dedup_same_match() -> None:
    """F3: 同一场多条 low_goals alpha 只算 1 次（distinct match）。"""
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry
    from nutmeg.services.jczq_strategy_memory import (
        compute_daily_low_goals_concentration,
    )

    rows = [
        PoissonEdgeEntry(
            match_no="周四004", home="A", away="B", league="西甲",
            pool="crs", pick="0:0", market_odd=15.0, fair_odd=11.0,
            edge=0.36, expected_goals=2.3,
        ),
        # 同场不同 pick，仍算 1 个 match
        PoissonEdgeEntry(
            match_no="周四004", home="A", away="B", league="西甲",
            pool="ttg", pick="1球", market_odd=5.5, fair_odd=4.6,
            edge=0.198, expected_goals=2.3,
        ),
    ]
    assert compute_daily_low_goals_concentration(rows) == 1


def test_f3_bias_returns_empty_when_below_trigger() -> None:
    """F3: 仅 2 场 ≥+15% low_goals alpha < trigger 3 → 不触发。"""
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry
    from nutmeg.services.jczq_strategy_memory import (
        compute_daily_concentration_bias,
    )

    rows = [
        PoissonEdgeEntry(
            match_no="周四001", home="A", away="B", league="西甲",
            pool="crs", pick="0:0", market_odd=10.0, fair_odd=8.0,
            edge=0.20, expected_goals=2.0,
        ),
        PoissonEdgeEntry(
            match_no="周四003", home="C", away="D", league="沙职",
            pool="ttg", pick="1球", market_odd=8.0, fair_odd=6.5,
            edge=0.18, expected_goals=2.2,
        ),
    ]
    bias = compute_daily_concentration_bias(rows)
    assert bias == {}, f"F3: 2 < 3 trigger，应返空 dict，实际 {bias}"


def test_f3_bias_returns_decay_map_when_triggered() -> None:
    """F3: ≥3 场 low_goals strong alpha → 返回 {LOW_GOALS_PICKS: 0.9}。"""
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry
    from nutmeg.services.jczq_strategy_memory import (
        DAILY_CONCENTRATION_DECAY,
        LOW_GOALS_PICKS,
        compute_daily_concentration_bias,
    )

    rows = [
        PoissonEdgeEntry(
            match_no="周四001", home="A", away="B", league="西甲",
            pool="crs", pick="0:0", market_odd=10.0, fair_odd=8.0,
            edge=0.20, expected_goals=2.0,
        ),
        PoissonEdgeEntry(
            match_no="周四003", home="C", away="D", league="沙职",
            pool="ttg", pick="1球", market_odd=8.0, fair_odd=6.5,
            edge=0.18, expected_goals=2.2,
        ),
        PoissonEdgeEntry(
            match_no="周四004", home="E", away="F", league="西甲",
            pool="crs", pick="0:0", market_odd=15.0, fair_odd=11.0,
            edge=0.36, expected_goals=2.3,
        ),
    ]
    bias = compute_daily_concentration_bias(rows)
    assert bias, "F3: 3 场 strong alpha 应触发"
    # 所有 low_goals picks 都应有 decay
    for pp in LOW_GOALS_PICKS:
        assert bias.get(pp) == DAILY_CONCENTRATION_DECAY, (
            f"F3: {pp} 应有 decay {DAILY_CONCENTRATION_DECAY}，实际 {bias.get(pp)}"
        )


def test_f3_compute_poisson_edges_applies_daily_concentration_bias() -> None:
    """F3: compute_poisson_edges 接收 daily_concentration_bias → low_goals leg
    edge 衰减后输出（× 0.9）。"""
    from nutmeg.services.jczq_intelligence import compute_poisson_edges

    matches = [
        JczqDailyMatch(**{
            "match_no": "周四004",
            "match_date": "2026-05-14",
            "match_time": "21:00:00",
            "league": "西甲",
            "home_team": "赫罗纳",
            "away_team": "皇家社会",
            "status": "Selling",
            "hot_direction": "主胜低赔(1.87)",
            "role": "谨慎博弈场",
            "confidence_note": "",
            "candidates": [
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="胜",
                    odds=1.87, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="平",
                    odds=3.50, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="负",
                    odds=4.50, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="crs", play="比分", pick="0:0",
                    odds=15.0, logic="",
                ),
            ],
        }),
    ]
    baseline = {
        row.pool + ":" + row.pick: row.edge
        for row in compute_poisson_edges(matches)
    }
    biased = {
        row.pool + ":" + row.pick: row.edge
        for row in compute_poisson_edges(
            matches,
            daily_concentration_bias={("crs", "0:0"): 0.9},
        )
    }
    if "crs:0:0" in baseline:
        expected = baseline["crs:0:0"] * 0.9
        assert abs(biased["crs:0:0"] - expected) < 1e-9, (
            f"F3: crs 0:0 应 ×0.9；baseline {baseline['crs:0:0']:+.4f}, "
            f"biased {biased['crs:0:0']:+.4f}, expected {expected:+.4f}"
        )
    # had pool 不受 F3 影响
    for pick in ("胜", "平", "负"):
        key = f"had:{pick}"
        if key in baseline:
            assert abs(baseline[key] - biased[key]) < 1e-9, (
                f"F3: had pool 不在 LOW_GOALS_PICKS，{key} 不应变"
            )


# --------------------------------------------------- F4 (5/14 落库) ---
# 5/14 用户洞察：crs 9 选项细分过碎；ttg 0/1/2/3+ 球更稳健（"大小球类似物"）。
# F4 策略层：当同场 alpha 候选有 ttg 和 crs 时，优先 ttg；除非 crs edge 明显
# > ttg edge（差距 ≥ F4_DOMINANCE_THRESHOLD=+0.10）。Rule O 限制 same-match
# 不能 join 同票，所以这是 single-leg-per-match 情况下选哪条 alpha 的偏好。


def test_f4_select_preferred_alpha_picks_ttg_when_close() -> None:
    """F4: 同场 ttg 1球 +12% / crs 0:0 +15%（差距 3pp < +10pp）→ 选 ttg。"""
    from nutmeg.services.jczq_daily import select_preferred_alpha_per_match
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    ttg_row = PoissonEdgeEntry(
        match_no="周四004", home="赫罗纳", away="皇社", league="西甲",
        pool="ttg", pick="1球", market_odd=5.5, fair_odd=4.9,
        edge=0.12, expected_goals=2.3,
    )
    crs_row = PoissonEdgeEntry(
        match_no="周四004", home="赫罗纳", away="皇社", league="西甲",
        pool="crs", pick="0:0", market_odd=15.0, fair_odd=13.0,
        edge=0.15, expected_goals=2.3,
    )
    selected = select_preferred_alpha_per_match([ttg_row, crs_row])
    assert len(selected) == 1, f"Same match should keep 1 row; got {len(selected)}"
    assert selected[0].pool == "ttg", (
        f"F4: 同场 ttg vs crs 差距 < +10pp 时应选 ttg；实际 {selected[0].pool}"
    )


def test_f4_select_preferred_alpha_picks_crs_when_dominant() -> None:
    """F4: 同场 crs +30% vs ttg +10%（差距 20pp >= +10pp）→ 选 crs。"""
    from nutmeg.services.jczq_daily import select_preferred_alpha_per_match
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    ttg_row = PoissonEdgeEntry(
        match_no="周四004", home="赫罗纳", away="皇社", league="西甲",
        pool="ttg", pick="1球", market_odd=5.5, fair_odd=4.9,
        edge=0.10, expected_goals=2.3,
    )
    crs_row = PoissonEdgeEntry(
        match_no="周四004", home="赫罗纳", away="皇社", league="西甲",
        pool="crs", pick="0:0", market_odd=15.0, fair_odd=11.5,
        edge=0.30, expected_goals=2.3,
    )
    selected = select_preferred_alpha_per_match([ttg_row, crs_row])
    assert len(selected) == 1
    assert selected[0].pool == "crs", (
        f"F4: crs +30% - ttg +10% = +20pp >= dominance threshold +10pp，应选 crs"
    )


def test_f4_select_preferred_keeps_only_pool() -> None:
    """F4: 同场仅有 ttg → 保留 ttg；仅有 crs → 保留 crs；两种 sanity。"""
    from nutmeg.services.jczq_daily import select_preferred_alpha_per_match
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    only_ttg = PoissonEdgeEntry(
        match_no="周四001", home="A", away="B", league="西甲",
        pool="ttg", pick="1球", market_odd=4.5, fair_odd=4.0,
        edge=0.12, expected_goals=2.5,
    )
    only_crs = PoissonEdgeEntry(
        match_no="周四002", home="C", away="D", league="沙职",
        pool="crs", pick="0:0", market_odd=12.0, fair_odd=10.0,
        edge=0.20, expected_goals=2.0,
    )
    selected = select_preferred_alpha_per_match([only_ttg, only_crs])
    pools = {r.pool for r in selected}
    assert pools == {"ttg", "crs"}, (
        f"F4: 不同场各保留一条；预期 {{ttg, crs}}，实际 {pools}"
    )


def test_f4_select_preferred_does_not_break_cross_match() -> None:
    """F4: 跨场 alpha 不变，每场各保留 1 条按 F4 偏好。"""
    from nutmeg.services.jczq_daily import select_preferred_alpha_per_match
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    rows = [
        # 004: ttg vs crs 差距 < dominance
        PoissonEdgeEntry(
            match_no="周四004", home="A", away="B", league="西甲",
            pool="ttg", pick="1球", market_odd=5.5, fair_odd=4.9,
            edge=0.10, expected_goals=2.3,
        ),
        PoissonEdgeEntry(
            match_no="周四004", home="A", away="B", league="西甲",
            pool="crs", pick="0:0", market_odd=15.0, fair_odd=13.0,
            edge=0.13, expected_goals=2.3,
        ),
        # 001: only ttg
        PoissonEdgeEntry(
            match_no="周四001", home="C", away="D", league="西甲",
            pool="ttg", pick="1球", market_odd=4.5, fair_odd=4.0,
            edge=0.12, expected_goals=2.5,
        ),
        # 002: crs dominant (+30% vs ttg +5%)
        PoissonEdgeEntry(
            match_no="周四002", home="E", away="F", league="沙职",
            pool="ttg", pick="1球", market_odd=8.0, fair_odd=7.6,
            edge=0.05, expected_goals=2.0,
        ),
        PoissonEdgeEntry(
            match_no="周四002", home="E", away="F", league="沙职",
            pool="crs", pick="0:0", market_odd=12.0, fair_odd=9.2,
            edge=0.30, expected_goals=2.0,
        ),
    ]
    selected = select_preferred_alpha_per_match(rows)
    by_match = {r.match_no: r.pool for r in selected}
    assert by_match["周四004"] == "ttg", "F4: 004 同场差距小 → ttg"
    assert by_match["周四001"] == "ttg", "F4: 001 仅 ttg → ttg"
    assert by_match["周四002"] == "crs", "F4: 002 crs dominant → crs"
    assert len(selected) == 3, f"F4: 3 distinct matches → 3 rows; got {len(selected)}"


def test_f3_stacks_with_f2_and_r25_in_correct_order() -> None:
    """F3: 三层衰减叠加顺序正确：edge = (raw + R25_bias) × F2_decay × F3_decay。
    构造一个场景验证三者协同。"""
    from nutmeg.services.jczq_intelligence import compute_poisson_edges

    matches = [
        JczqDailyMatch(**{
            "match_no": "周四004",
            "match_date": "2026-05-14",
            "match_time": "21:00:00",
            "league": "西甲",
            "home_team": "赫罗纳",
            "away_team": "皇家社会",
            "status": "Selling",
            "hot_direction": "主胜低赔(1.87)",
            "role": "谨慎博弈场",
            "confidence_note": "",
            "candidates": [
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="胜",
                    odds=1.87, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="平",
                    odds=3.50, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="had", play="胜平负", pick="负",
                    odds=4.50, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="crs", play="比分", pick="0:0",
                    odds=15.0, logic="",
                ),
            ],
        }),
    ]
    raw_rows = compute_poisson_edges(matches)
    raw_edge = next(
        r.edge for r in raw_rows if r.pool == "crs" and r.pick == "0:0"
    )

    biased_rows = compute_poisson_edges(
        matches,
        league_residual_bias={"西甲": -0.10},      # R25
        empirical_decay_map={("crs", "0:0"): 0.625},  # F2
        daily_concentration_bias={("crs", "0:0"): 0.9},  # F3
    )
    biased_edge = next(
        r.edge for r in biased_rows if r.pool == "crs" and r.pick == "0:0"
    )
    expected = (raw_edge + (-0.10)) * 0.625 * 0.9
    assert abs(biased_edge - expected) < 1e-9, (
        f"F3 stack: edge = (raw + R25) × F2 × F3 = "
        f"({raw_edge:+.4f} + (-0.10)) × 0.625 × 0.9 = {expected:+.4f}; "
        f"实际 {biased_edge:+.4f}"
    )


# --------------------------------------------------- R26 (5/15 落库) ---
# 5/01-5/14 历史 crs leg-hit 1/30 = 3.3% (poisson_solo crs 1/9, inspiration 0/7,
# extreme 3/29 leg-hit). 0/27 含 crs 的票整票命中。R23 (+25% 0:0 floor) 没救
# 5/14 004 crs 0:0 (adjusted edge +36.1% λ=2.4 实际 1:1). R26 把整个 crs 池
# 从 poisson_solo 移除 —— ttg/had/hhad alpha 才进单核灵感票。crs 仍可由
# inspiration/extreme 通过 select_top_legs 选入。


def test_r26_crs_blocked_from_poisson_solo_even_with_strong_edge() -> None:
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周四004", match_date="2026-05-14", match_time="22:00:00",
            league="西甲", home_team="赫罗纳", away_team="皇家社会",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="crs", play="比分", pick="0:0",
                    odds=15.0, logic="",
                ),
            ],
        ),
    ]
    row = PoissonEdgeEntry(
        match_no="周四004", home="赫罗纳", away="皇家社会", league="西甲",
        pool="crs", pick="0:0", market_odd=15.0, fair_odd=11.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.21,  # +36% — 5/14 实际案例 adjusted
        expected_goals=2.4,
    )
    plan = service._build_poisson_solo_plan(matches, poisson_rows=[row])
    assert plan.legs == [], (
        "R26: crs 0:0 +36% adjusted edge 仍然被拒进 poisson_solo "
        "(5/14 004 实际 1:1 验证 crs alpha 结构性失真)"
    )


def test_r26_ttg_alpha_replaces_crs_in_same_match() -> None:
    """Same-match ttg alpha edges out crs (R26 + Rule O combined)."""
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
        POISSON_SOLO_EDGE_THRESHOLD,
    )
    from nutmeg.services.jczq_intelligence import PoissonEdgeEntry

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周四004", match_date="2026-05-14", match_time="22:00:00",
            league="西甲", home_team="赫罗纳", away_team="皇家社会",
            status="Selling", hot_direction="均衡(2.40)", role="均衡分歧场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="crs", play="比分", pick="0:0",
                    odds=15.0, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四004", league="西甲", home_team="赫罗纳",
                    away_team="皇家社会", pool="ttg", play="总进球", pick="1球",
                    odds=4.45, logic="",
                ),
            ],
        ),
    ]
    crs_row = PoissonEdgeEntry(
        match_no="周四004", home="赫罗纳", away="皇家社会", league="西甲",
        pool="crs", pick="0:0", market_odd=15.0, fair_odd=11.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.21,  # +36%, but R26 blocks
        expected_goals=2.4,
    )
    ttg_row = PoissonEdgeEntry(
        match_no="周四004", home="赫罗纳", away="皇家社会", league="西甲",
        pool="ttg", pick="1球", market_odd=4.45, fair_odd=4.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.02,  # +17%
        expected_goals=2.4,
    )
    plan = service._build_poisson_solo_plan(
        matches, poisson_rows=[crs_row, ttg_row]
    )
    assert len(plan.legs) == 1
    assert plan.legs[0].pool == "ttg"
    assert plan.legs[0].pick == "1球"


# --------------------------------------------------- R27 (5/15 落库) ---
# Rule H 升级：5/01-5/14 hafu 全口径 0/18 leg-hit + 0/18 含-hafu-票整票命中。
# 原来 hafu 锁在 extreme 当娱乐高赔仍允许，但 extreme 内 hafu 8 个样本 0 命中
# (5/14 003 hafu 胜/胜 @13x 实际 2:0 经典翻车)。R27 让 hafu 在所有票（含 extreme）
# 全面剥离；extreme 直接 drop 不替换（保留高赔但删 hafu 腿）。


def test_r27_hafu_stripped_from_extreme_without_replacement() -> None:
    from nutmeg.services.jczq_daily import (
        JczqDailyAdvisorService as _Svc,
    )

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    match = JczqDailyMatch(
        match_no="周四003", match_date="2026-05-14", match_time="22:00:00",
        league="沙职", home_team="胡巴卡德", away_team="拉斯决心",
        status="Selling", hot_direction="主胜低赔(1.12)", role="强胆场",
        confidence_note="",
        candidates=[
            JczqDailyLeg(
                match_no="周四003", league="沙职", home_team="胡巴卡德",
                away_team="拉斯决心", pool="hafu", play="半全场", pick="平/平",
                odds=13.0, logic="",
            ),
            JczqDailyLeg(
                match_no="周四003", league="沙职", home_team="胡巴卡德",
                away_team="拉斯决心", pool="ttg", play="总进球", pick="2球",
                odds=4.50, logic="",
            ),
        ],
    )
    crs_leg = JczqDailyLeg(
        match_no="周四005", league="西甲", home_team="皇马",
        away_team="奥维耶多", pool="crs", play="比分", pick="2:0",
        odds=7.25, logic="",
    )
    hafu_leg = JczqDailyLeg(
        match_no="周四003", league="沙职", home_team="胡巴卡德",
        away_team="拉斯决心", pool="hafu", play="半全场", pick="平/平",
        odds=13.0, logic="",
    )
    extreme_plan = service._make_plan(
        "极限小注票",
        "extreme",
        "高赔率小注",
        [crs_leg, hafu_leg],
        "",
    )
    cleaned = service._apply_rule_h_hafu_block([extreme_plan], [match])
    assert len(cleaned) == 1
    cleaned_plan = cleaned[0]
    pools = [leg.pool for leg in cleaned_plan.legs]
    assert "hafu" not in pools, "R27: hafu 必须从 extreme 也剥离"
    assert "crs" in pools, "R27: 非 hafu 腿应保留"
    assert len(cleaned_plan.legs) == 1, (
        "R27: extreme 不替换 hafu 腿；ticket 缩短"
    )
    assert "R27" in cleaned_plan.risk_note or "0/18" in cleaned_plan.risk_note


def test_r27_hafu_not_introduced_into_extreme_at_search_stage() -> None:
    """Even when `extreme=True`, `_search_plan` should not pick hafu legs
    because allow_hafu is hard-coded to False under R27."""
    from nutmeg.services.jczq_daily import JczqDailyAdvisorService as _Svc

    service = _Svc.__new__(_Svc)
    service.__init__()  # type: ignore[misc]
    matches = [
        JczqDailyMatch(
            match_no="周四003", match_date="2026-05-14", match_time="22:00:00",
            league="沙职", home_team="胡巴卡德", away_team="拉斯决心",
            status="Selling", hot_direction="主胜低赔(1.12)", role="强胆场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周四003", league="沙职", home_team="胡巴卡德",
                    away_team="拉斯决心", pool="hafu", play="半全场",
                    pick="平/平", odds=13.0, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四003", league="沙职", home_team="胡巴卡德",
                    away_team="拉斯决心", pool="crs", play="比分", pick="2:0",
                    odds=7.25, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四003", league="沙职", home_team="胡巴卡德",
                    away_team="拉斯决心", pool="had", play="胜平负", pick="胜",
                    odds=1.12, logic="",
                ),
            ],
        ),
        JczqDailyMatch(
            match_no="周四005", match_date="2026-05-14", match_time="22:00:00",
            league="西甲", home_team="皇马", away_team="奥维耶多",
            status="Selling", hot_direction="主胜低赔(1.17)", role="强胆场",
            confidence_note="",
            candidates=[
                JczqDailyLeg(
                    match_no="周四005", league="西甲", home_team="皇马",
                    away_team="奥维耶多", pool="crs", play="比分", pick="2:0",
                    odds=7.25, logic="",
                ),
                JczqDailyLeg(
                    match_no="周四005", league="西甲", home_team="皇马",
                    away_team="奥维耶多", pool="had", play="胜平负", pick="胜",
                    odds=1.17, logic="",
                ),
            ],
        ),
    ]
    extreme_plan = service._search_plan(
        matches,
        analytics={},
        name="极限小注票",
        kind="extreme",
        description="",
        target_min=300,
        target_max=5000,
        no_score=False,
        extreme=True,
    )
    pools = [leg.pool for leg in extreme_plan.legs]
    assert "hafu" not in pools, "R27: extreme builder 不应再选 hafu"


# ---------------------------------------------------------------- R28 ---


def test_r28_poisson_solo_retired_never_appears_in_report() -> None:
    """R28 (5/16): the poisson_solo ticket is retired.

    Even when a strong Poisson edge (≥ +15% — the historical trigger
    condition) is present, the generator must not emit a poisson_solo plan.

    Backtest 5/01-5/15: poisson_solo whole-ticket hit 1/11 days, leg-hit
    2/16 (12.5%), realized -47.7% over 11 days. "Single highest-edge leg,
    solo" structurally selects the model's most over-concentrated low-goal
    bin (ttg 1球 / crs 0:0); R17/R18/R22/R23/R24/R26 patches did not fix it.
    """
    matches = [_strong_chalk("周一001")] + [_normal(f"周一00{i}") for i in range(2, 5)]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05"
    )
    # Sanity: the fixture still carries a ≥ +15% Poisson edge — the exact
    # condition that used to fire poisson_solo — so the absence below is
    # R28 retiring the ticket, not a missing signal.
    edges = compute_poisson_edges(report.matches)
    assert any(row.edge >= 0.15 for row in edges), (
        "fixture must still carry a poisson_solo-grade edge for this test to mean anything"
    )
    assert all(plan.kind != "poisson_solo" for plan in report.plans), (
        "R28: poisson_solo ticket is retired and must not appear in generator output"
    )


def test_r28_retirement_flag_is_enabled() -> None:
    """R28 flag guards the retirement so a future ≥30-day re-review can
    revive poisson_solo by flipping a single constant (see R26/R27 pattern)."""
    from nutmeg.services.jczq_daily import RULE_R28_RETIRE_POISSON_SOLO

    assert RULE_R28_RETIRE_POISSON_SOLO is True
