from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.config.settings import get_settings
from nutmeg.domain.odds import OddsProviderEvent
from nutmeg.storage.bootstrap import create_analytics_schema
from nutmeg.storage.odds_repository import DuckDbOddsEventRepository


def test_duckdb_odds_event_repository_round_trips_provider_event() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbOddsEventRepository(settings)

    repository.upsert_event(
        OddsProviderEvent(
            fixture_id='1234',
            provider='the-odds-api',
            sport_key='soccer_epl',
            event_id='event-123',
            home_team='Liverpool',
            away_team='Crystal Palace',
            commence_time=datetime(2026, 4, 25, 14, 2, tzinfo=UTC),
            matched_at=datetime(2026, 4, 24, 6, 0, tzinfo=UTC),
        )
    )

    event = repository.get_event('1234', provider='the-odds-api')

    assert event is not None
    assert event.event_id == 'event-123'
    assert event.sport_key == 'soccer_epl'
    assert event.home_team == 'Liverpool'


def test_duckdb_odds_event_repository_deletes_only_selected_provider_mapping() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbOddsEventRepository(settings)

    repository.upsert_event(
        OddsProviderEvent(
            fixture_id='1234',
            provider='the-odds-api',
            sport_key='soccer_epl',
            event_id='event-123',
            home_team='Liverpool',
            away_team='Crystal Palace',
            commence_time=datetime(2026, 4, 25, 14, 2, tzinfo=UTC),
            matched_at=datetime(2026, 4, 24, 6, 0, tzinfo=UTC),
        )
    )
    repository.upsert_event(
        OddsProviderEvent(
            fixture_id='1234',
            provider='other-provider',
            sport_key='soccer_epl',
            event_id='other-event',
            home_team='Liverpool',
            away_team='Crystal Palace',
            commence_time=datetime(2026, 4, 25, 14, 2, tzinfo=UTC),
            matched_at=datetime(2026, 4, 24, 6, 0, tzinfo=UTC),
        )
    )

    repository.delete_event('1234', provider='the-odds-api')

    assert repository.get_event('1234', provider='the-odds-api') is None
    other_event = repository.get_event('1234', provider='other-provider')
    assert other_event is not None
    assert other_event.event_id == 'other-event'
