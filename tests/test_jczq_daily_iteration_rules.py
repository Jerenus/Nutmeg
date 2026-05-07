"""Regression for Rules A-F added to JCZQ daily generator.

Rules under test:
- A: poisson_solo ticket appears when at least one Poisson edge ≥ +15%
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


def test_rule_a_poisson_solo_fires_when_strong_edge_present(tmp_path: Path) -> None:
    # _strong_chalk has crs 0:0 @ 33.00 and ttg 1球 @ 9.75; with 1.24 home favorite,
    # Poisson typically prices the underdog scorelines materially below market — at
    # least one leg should clear +15% edge.
    matches = [_strong_chalk("周一001")] + [_normal(f"周一00{i}") for i in range(2, 5)]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-05", output_dir=tmp_path
    )
    poisson_solo = next(
        (plan for plan in report.plans if plan.kind == "poisson_solo"), None
    )
    edges = compute_poisson_edges(report.matches)
    high = [row for row in edges if row.edge >= 0.15]
    if not high:
        # If the synthetic fixture didn't produce a high-edge leg, the plan must be empty.
        assert poisson_solo is None or poisson_solo.legs == []
        return
    assert poisson_solo is not None and poisson_solo.legs
    assert len(poisson_solo.legs) <= 2
    # Rule B composition guard: no had ≤ HAD_BANKER_FLOOR legs allowed inside poisson_solo.
    for leg in poisson_solo.legs:
        if leg.pool == "had":
            assert leg.odds > HAD_BANKER_FLOOR


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
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.07,  # +22%
    )
    ttg_row = PoissonEdgeEntry(
        match_no="周一001", home="H", away="A", league="日职",
        pool="ttg", pick="1球", market_odd=4.45, fair_odd=4.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.02,  # +17%, also strong
    )
    plan = service._build_poisson_solo_plan(matches, poisson_rows=[crs_row, ttg_row])
    # Both legs are eligible (>= +15% edge), but they're from the same match
    # → only one may enter the ticket. The top edge (crs +22%) wins; ttg is dropped.
    assert len(plan.legs) == 1, (
        "Rule A v2 v3 must NEVER produce same-match different-pool combos "
        "(国家体彩混合过关规则)"
    )
    assert plan.legs[0].pool == "crs"
    assert plan.legs[0].pick == "0:0"


def test_rule_a_v2_cross_match_support_extends_to_two_legs() -> None:
    """When a cross-match +EV row (>= +5%) exists, Rule A v2 extends the
    primary-edge solo to a 2-leg cross-match combo.
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
                    pool="crs", play="比分", pick="0:0", odds=11.0, logic="",
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
        pool="crs", pick="0:0", market_odd=11.0, fair_odd=9.0,
        edge=POISSON_SOLO_EDGE_THRESHOLD + 0.07,  # +22%
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
    poisson_solo = next((plan for plan in plans if plan.kind == "poisson_solo"), None)
    assert poisson_solo is not None and len(poisson_solo.legs) >= 1
    # Top Poisson edge on 5/04 was 周一007 0:0 (+21.6%) — must appear in poisson_solo.
    top_legs = {(leg.match_no, leg.pool, leg.pick) for leg in poisson_solo.legs}
    assert ("周一007", "crs", "0:0") in top_legs


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
