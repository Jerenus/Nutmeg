from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.services.popularity import MatchPopularityRanker


def _fixture(
    fixture_id: str,
    *,
    home_team: str,
    away_team: str,
    kickoff_at: datetime,
    league_code: str = 'epl',
    status: FixtureStatus = FixtureStatus.SCHEDULED,
) -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        league_code=league_code,
        provider_league_id=39,
        season=2025,
        kickoff_at=kickoff_at,
        home_team_id=None,
        away_team_id=None,
        home_team=home_team,
        away_team=away_team,
        status=status,
    )


def test_popularity_ranker_prioritizes_elite_matchup_with_explainable_score() -> None:
    now = datetime(2026, 4, 25, 12, tzinfo=UTC)
    local_soon = _fixture(
        'epl-small',
        home_team='Brentford',
        away_team='Fulham',
        kickoff_at=now + timedelta(hours=2),
    )
    elite_later = _fixture(
        'epl-headline',
        home_team='Manchester City',
        away_team='Liverpool',
        kickoff_at=now + timedelta(days=2),
    )

    ranked = MatchPopularityRanker().rank([local_soon, elite_later], now=now, limit=2)

    assert [item.fixture.fixture_id for item in ranked] == ['epl-headline', 'epl-small']
    assert ranked[0].rank == 1
    assert ranked[0].popularity.score > ranked[1].popularity.score
    assert ranked[0].popularity.tier == 'headline'
    assert any('major teams' in reason for reason in ranked[0].popularity.reasons)
    assert any('elite matchup' in reason for reason in ranked[0].popularity.reasons)


def test_popularity_ranker_boosts_live_fixtures() -> None:
    now = datetime(2026, 4, 25, 12, tzinfo=UTC)
    live_fixture = _fixture(
        'epl-live',
        home_team='Everton',
        away_team='West Ham United',
        kickoff_at=now - timedelta(minutes=20),
        status=FixtureStatus.LIVE,
    )
    scheduled_fixture = _fixture(
        'epl-later',
        home_team='Everton',
        away_team='West Ham United',
        kickoff_at=now + timedelta(days=2),
    )

    ranked = MatchPopularityRanker().rank([scheduled_fixture, live_fixture], now=now, limit=2)

    assert ranked[0].fixture.fixture_id == 'epl-live'
    assert any('live now' in reason for reason in ranked[0].popularity.reasons)
