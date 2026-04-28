from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from nutmeg.config.settings import get_settings
from nutmeg.data.api_football import ApiQuota, FixtureBatch
from nutmeg.domain.fixtures import FixtureStatus, sample_fixtures
from nutmeg.services.sync import FixtureSyncService
from nutmeg.storage.bootstrap import (
    build_state_engine,
    create_analytics_schema,
    create_state_schema,
)
from nutmeg.storage.fixture_repository import DuckDbFixtureRepository
from nutmeg.storage.sync_run_repository import SqlAlchemySyncRunRepository


class FakeApiClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch_upcoming_fixtures(self, **kwargs):
        self.calls.append(kwargs)
        league_code = kwargs['league_code']
        fixtures = sample_fixtures(league_code)
        if kwargs['date_from'] < date(2026, 4, 24):
            fixtures = [
                fixtures[0],
                fixtures[1],
                fixtures[0].__class__(
                    fixture_id=f'{league_code}-past-001',
                    league_code=league_code,
                    provider_league_id=fixtures[0].provider_league_id,
                    season=fixtures[0].season,
                    kickoff_at=datetime.combine(
                        kwargs['date_from'],
                        datetime.min.time(),
                        tzinfo=UTC,
                    ),
                    home_team_id=fixtures[0].home_team_id,
                    away_team_id=fixtures[1].away_team_id,
                    home_team=fixtures[0].home_team,
                    away_team=fixtures[1].away_team,
                    source='api-football',
                    status=FixtureStatus.FINISHED,
                    status_short='FT',
                    status_long='Match Finished',
                    home_goals=2,
                    away_goals=1,
                ),
            ]
        return FixtureBatch(
            fixtures=fixtures,
            requests_made=1,
            quota=ApiQuota(requests_remaining=7000, minute_remaining=59),
        )

    def close(self) -> None:
        return None


class FailingApiClient:
    def fetch_upcoming_fixtures(self, **kwargs):
        raise RuntimeError('boom')

    def close(self) -> None:
        return None


def test_sync_service_writes_shared_fixtures_and_sync_metadata() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    engine = build_state_engine(settings)
    create_state_schema(engine)
    session = Session(engine)
    try:
        service = FixtureSyncService(
            fixture_repository=DuckDbFixtureRepository(settings),
            sync_run_repository=SqlAlchemySyncRunRepository(session),
            api_client=FakeApiClient(),
        )

        report = service.sync(
            league_codes=['epl', 'ucl'],
            days=14,
            timezone='UTC',
            now=datetime(2026, 4, 24, tzinfo=UTC),
        )
        session.commit()
        latest = SqlAlchemySyncRunRepository(session).latest()
    finally:
        session.close()

    assert report.total_fixtures == 4
    assert report.total_requests == 2
    assert latest is not None
    assert latest.status == 'success'
    assert latest.fixtures_written == 4


def test_sync_service_marks_failure_when_provider_raises() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    engine = build_state_engine(settings)
    create_state_schema(engine)
    session = Session(engine)
    repository = SqlAlchemySyncRunRepository(session)
    service = FixtureSyncService(
        fixture_repository=DuckDbFixtureRepository(settings),
        sync_run_repository=repository,
        api_client=FailingApiClient(),
    )

    try:
        with pytest.raises(RuntimeError, match='boom'):
            service.sync(
                league_codes=['epl'],
                days=14,
                timezone='UTC',
                now=datetime(2026, 4, 24, tzinfo=UTC),
            )
        session.commit()
        latest = repository.latest()
    finally:
        session.close()

    assert latest is not None
    assert latest.status == 'failed'

def test_sync_service_can_include_historical_fixture_window() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    engine = build_state_engine(settings)
    create_state_schema(engine)
    session = Session(engine)
    api_client = FakeApiClient()
    try:
        service = FixtureSyncService(
            fixture_repository=DuckDbFixtureRepository(settings),
            sync_run_repository=SqlAlchemySyncRunRepository(session),
            api_client=api_client,
        )

        report = service.sync(
            league_codes=['epl'],
            days=7,
            past_days=3,
            timezone='UTC',
            now=datetime(2026, 4, 24, tzinfo=UTC),
        )
        session.commit()
    finally:
        session.close()

    assert report.total_fixtures == 3
    assert api_client.calls[0]['date_from'].isoformat() == '2026-04-21'
    assert api_client.calls[0]['date_to'].isoformat() == '2026-05-01'

