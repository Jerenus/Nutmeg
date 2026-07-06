"""worldcup.results — 从 Fixture 摄取世界杯赛果(90 分钟口径 + 晋级方)。"""
from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.services.worldcup.results import ingest_results
from nutmeg.services.worldcup.tournament import Tournament
from tests.test_wc_tournament import _mini_tournament_dict


def _fixture(home: str, away: str, status_short: str, gh: int, ga: int,
             pen_h: int | None = None, pen_a: int | None = None) -> Fixture:
    return Fixture(
        fixture_id=f"fx-{home}-{away}", league_code="WC2026",
        provider_league_id=1, season=2026,
        kickoff_at=datetime(2026, 6, 11, 18, tzinfo=UTC),
        home_team_id=1, away_team_id=2, home_team=home, away_team=away,
        status=FixtureStatus.FINISHED, status_short=status_short,
        home_goals=gh, away_goals=ga,
        penalty_home=pen_h, penalty_away=pen_a,
    )


def _tournament() -> Tournament:
    return Tournament.from_dict(_mini_tournament_dict())


def test_ingest_ft_match_records_90min_outcome() -> None:
    out = ingest_results([_fixture("Mexico", "Poland", "FT", 2, 1)],
                         _tournament(), existing=[])
    assert len(out) == 1
    r = out[0]
    assert (r.match_id, r.outcome_90, r.goals_h_90, r.goals_a_90) == ("M01", "home", 2, 1)
    assert r.advanced is None  # 小组赛无晋级方概念


def test_ingest_aet_is_draw_at_90_with_winner_advanced() -> None:
    out = ingest_results([_fixture("Mexico", "Poland", "AET", 2, 1)],
                         _tournament(), existing=[])
    r = out[0]
    assert r.outcome_90 == "draw"
    assert r.goals_h_90 is None  # 90 分钟比分不可知,只知道平
    assert r.advanced == "Mexico"


def test_ingest_pen_uses_penalty_score() -> None:
    out = ingest_results([_fixture("Mexico", "Poland", "PEN", 1, 1, 4, 3)],
                         _tournament(), existing=[])
    assert out[0].advanced == "Mexico"


def test_ingest_is_idempotent_and_ignores_unknown() -> None:
    existing = ingest_results([_fixture("Mexico", "Poland", "FT", 2, 1)],
                              _tournament(), existing=[])
    again = ingest_results(
        [_fixture("Mexico", "Poland", "FT", 2, 1),
         _fixture("Arsenal", "Liverpool", "FT", 1, 0)],  # 非世界杯队 → 忽略
        _tournament(), existing=existing,
    )
    assert len(again) == 1


def test_canonical_maps_api_alternate_spelling_to_seed() -> None:
    """2026-07-06 code-review 修复:_API_NAME_FIXES 方向必须【API 别名→种子】。
    早先 USA/Türkiye 写反成死条目,恰好救不了它们本要修的漏结。"""
    from nutmeg.services.worldcup.results import _canonical

    teams = {"USA", "Türkiye", "South Korea", "Czech Republic", "Cape Verde Islands"}
    assert _canonical("United States", teams) == "USA"
    assert _canonical("Turkey", teams) == "Türkiye"
    assert _canonical("Korea Republic", teams) == "South Korea"
    assert _canonical("Czechia", teams) == "Czech Republic"
    assert _canonical("Cabo Verde", teams) == "Cape Verde Islands"
    assert _canonical("USA", teams) == "USA"          # 已是种子 → 原样
    assert _canonical("Neverland", teams) == "Neverland"  # 未知 → 原样(交给上层丢弃)
