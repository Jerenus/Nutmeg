from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings, clear_settings_cache
from nutmeg.data.the_odds_api import TheOddsApiClient, TheOddsApiHealthSnapshot
from nutmeg.interfaces.cli import app
from nutmeg.storage.bootstrap import create_analytics_schema
from nutmeg.storage.odds_repository import (
    DuckDbOddsProviderHealthRepository,
)
from tests.test_the_odds_api import FakeFixtureRepository, InMemoryOddsEventRepository, _fixture

runner = CliRunner()


def _settings(tmp_path) -> AppSettings:
    return AppSettings(data_dir=tmp_path / 'nutmeg-data')


def test_duckdb_provider_health_repository_round_trips_latest_snapshot(tmp_path) -> None:
    settings = _settings(tmp_path)
    create_analytics_schema(settings)
    repository = DuckDbOddsProviderHealthRepository(settings)

    repository.record_snapshot(
        TheOddsApiHealthSnapshot(
            provider='the-odds-api',
            cache_hits=2,
            cache_misses=1,
            reconcile_attempts=3,
            reconcile_failures=1,
            stale_refresh_attempts=1,
            stale_refresh_successes=0,
            last_event_id='event-123',
            last_error='replacement reconciliation failed',
            updated_at=datetime(2026, 4, 25, 8, 0, tzinfo=UTC),
        )
    )

    latest = repository.get_latest('the-odds-api')

    assert latest is not None
    assert latest.provider == 'the-odds-api'
    assert latest.cache_hits == 2
    assert latest.cache_misses == 1
    assert latest.reconcile_attempts == 3
    assert latest.reconcile_failures == 1
    assert latest.stale_refresh_attempts == 1
    assert latest.stale_refresh_successes == 0
    assert latest.last_event_id == 'event-123'
    assert latest.last_error == 'replacement reconciliation failed'
    assert latest.updated_at == datetime(2026, 4, 25, 8, 0, tzinfo=UTC)


def test_the_odds_api_client_persists_health_for_next_instance(tmp_path) -> None:
    settings = _settings(tmp_path)
    create_analytics_schema(settings)
    health_repository = DuckDbOddsProviderHealthRepository(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/sports/soccer_epl/events':
            return httpx.Response(
                200,
                json=[
                    {
                        'id': 'event-123',
                        'sport_key': 'soccer_epl',
                        'commence_time': '2026-04-25T14:02:00Z',
                        'home_team': 'Liverpool',
                        'away_team': 'Crystal Palace',
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                'id': 'event-123',
                'sport_key': 'soccer_epl',
                'commence_time': '2026-04-25T14:02:00Z',
                'home_team': 'Liverpool',
                'away_team': 'Crystal Palace',
                'bookmakers': [],
            },
        )

    first_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=InMemoryOddsEventRepository(),
        health_repository=health_repository,
        client=httpx.Client(
            base_url='https://example.test',
            transport=httpx.MockTransport(handler),
        ),
    )

    first_client.fetch_fixture_odds('1234')
    latest = DuckDbOddsProviderHealthRepository(settings).get_latest('the-odds-api')

    assert latest is not None
    assert latest.cache_misses == 1
    assert latest.reconcile_attempts == 1
    assert latest.last_event_id == 'event-123'


def test_agent_status_reports_persisted_the_odds_api_health_without_network(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv('NUTMEG_DATA_DIR', str(tmp_path / 'nutmeg-data'))
    monkeypatch.setenv('NUTMEG_ODDS_PROVIDER', 'the-odds-api')
    monkeypatch.setenv('NUTMEG_THE_ODDS_API_KEY', 'odds-secret')
    clear_settings_cache()

    settings = _settings(tmp_path)
    create_analytics_schema(settings)
    health_repository = DuckDbOddsProviderHealthRepository(settings)
    health_repository.record_snapshot(
        TheOddsApiHealthSnapshot(
            provider='the-odds-api',
            cache_hits=4,
            cache_misses=2,
            reconcile_attempts=3,
            reconcile_failures=1,
            stale_refresh_attempts=1,
            stale_refresh_successes=1,
            last_event_id='event-456',
            last_error=None,
            updated_at=datetime(2026, 4, 25, 9, 30, tzinfo=UTC),
        )
    )

    result = runner.invoke(app, ['agent-status', '--format', 'json'])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload['odds_provider']['name'] == 'the-odds-api'
    assert payload['odds_provider']['health']['cache_hits'] == 4
    assert payload['odds_provider']['health']['cache_misses'] == 2
    assert payload['odds_provider']['health']['last_event_id'] == 'event-456'
    assert payload['odds_provider']['health']['updated_at'] == '2026-04-25T09:30:00+00:00'
    assert 'odds-secret' not in result.stdout
