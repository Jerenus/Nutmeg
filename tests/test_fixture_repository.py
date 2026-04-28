from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from nutmeg.config.settings import get_settings
from nutmeg.domain.fixtures import FixtureStatus, sample_fixtures
from nutmeg.storage.bootstrap import create_analytics_schema
from nutmeg.storage.fixture_repository import DuckDbFixtureRepository


def test_duckdb_fixture_repository_round_trips_fixtures() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbFixtureRepository(settings)
    fixtures = sample_fixtures('epl')
    fixtures[0] = replace(fixtures[0], referee='Michael Oliver')

    written = repository.upsert_many(fixtures)
    fixtures = repository.list_upcoming('epl', 7)
    fixture = repository.get_fixture('epl-001')

    assert written == 2
    assert len(fixtures) == 2
    assert fixtures[0].home_team == 'Arsenal'
    assert fixture is not None
    assert fixture.home_team_id == 42
    assert fixture.away_team_id == 148
    assert fixture.away_team == 'Tottenham Hotspur'
    assert fixture.referee == 'Michael Oliver'

def test_duckdb_fixture_repository_finds_latest_finished_fixture_before_kickoff() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbFixtureRepository(settings)
    target = sample_fixtures('epl')[0]
    target = replace(
        target,
        fixture_id='target',
        kickoff_at=datetime(2026, 4, 25, 14, tzinfo=UTC),
    )
    older = replace(
        target,
        fixture_id='older',
        kickoff_at=target.kickoff_at - timedelta(days=8),
        status=FixtureStatus.FINISHED,
        status_short='FT',
        home_goals=1,
        away_goals=0,
    )
    latest = replace(
        target,
        fixture_id='latest',
        kickoff_at=target.kickoff_at - timedelta(days=4),
        status=FixtureStatus.FINISHED,
        status_short='FT',
        home_goals=2,
        away_goals=1,
    )
    unfinished = replace(
        target,
        fixture_id='unfinished',
        kickoff_at=target.kickoff_at - timedelta(days=2),
        status=FixtureStatus.SCHEDULED,
        status_short='NS',
    )
    future = replace(
        target,
        fixture_id='future',
        kickoff_at=target.kickoff_at + timedelta(days=1),
        status=FixtureStatus.FINISHED,
        status_short='FT',
    )

    repository.upsert_many([target, older, latest, unfinished, future])

    previous = repository.get_latest_finished_for_team_before(
        league='epl',
        team_id=target.home_team_id,
        team_name=target.home_team,
        before=target.kickoff_at,
    )

    assert previous is not None
    assert previous.fixture_id == 'latest'


def test_duckdb_fixture_repository_returns_none_without_finished_prior_fixture() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbFixtureRepository(settings)
    target = replace(
        sample_fixtures('epl')[0],
        fixture_id='target-no-prior',
        kickoff_at=datetime(2026, 4, 25, 14, tzinfo=UTC),
    )
    repository.upsert_many([target])

    previous = repository.get_latest_finished_for_team_before(
        league='epl',
        team_id=target.home_team_id,
        team_name=target.home_team,
        before=target.kickoff_at,
    )

    assert previous is None
