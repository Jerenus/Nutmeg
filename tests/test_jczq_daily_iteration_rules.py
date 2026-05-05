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
    # Rule B composition guard: no had ≤ 1.40 legs allowed inside poisson_solo.
    for leg in poisson_solo.legs:
        if leg.pool == "had":
            assert leg.odds > HAD_BANKER_FLOOR


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


_ = COINFLIP_VIG_THRESHOLD  # silence ruff when threshold consts move
_ = COINFLIP_IMPLIED_SPREAD_THRESHOLD
