from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from nutmeg.domain.fixtures import Fixture, FixtureStatus


def _fixture() -> Fixture:
    return Fixture(
        fixture_id='1234',
        league_code='epl',
        provider_league_id=39,
        season=2025,
        kickoff_at=datetime(2026, 4, 25, 14, 0, tzinfo=UTC),
        home_team_id=40,
        away_team_id=52,
        home_team='Liverpool',
        away_team='Crystal Palace',
        source='api-football',
        status=FixtureStatus.SCHEDULED,
        status_short='NS',
        status_long='Not Started',
        venue='Anfield',
    )


class FakeFixtureRepository:
    def __init__(self, fixture: Fixture | None) -> None:
        self._fixture = fixture

    def get_fixture(self, fixture_id: str) -> Fixture | None:
        if self._fixture is None or self._fixture.fixture_id != fixture_id:
            return None
        return self._fixture


class InMemoryOddsEventRepository:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], object] = {}

    def get_event(self, fixture_id: str, *, provider: str):
        return self._events.get((fixture_id, provider))

    def upsert_event(self, event) -> None:
        self._events[(event.fixture_id, event.provider)] = event

    def delete_event(self, fixture_id: str, *, provider: str) -> None:
        self._events.pop((fixture_id, provider), None)


def test_fetch_fixture_odds_reconciles_event_and_normalizes_supported_markets() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/sports/soccer_epl/events':
            return httpx.Response(
                200,
                json=[
                    {
                        'id': 'event-123',
                        'sport_key': 'soccer_epl',
                        'sport_title': 'Premier League',
                        'commence_time': '2026-04-25T14:02:00Z',
                        'home_team': 'Liverpool',
                        'away_team': 'Crystal Palace',
                    }
                ],
            )
        assert request.url.path == '/sports/soccer_epl/events/event-123/odds'
        return httpx.Response(
            200,
            json={
                'id': 'event-123',
                'sport_key': 'soccer_epl',
                'sport_title': 'Premier League',
                'commence_time': '2026-04-25T14:02:00Z',
                'home_team': 'Liverpool',
                'away_team': 'Crystal Palace',
                'bookmakers': [
                    {
                        'key': 'bet365',
                        'title': 'Bet365',
                        'last_update': '2026-04-24T06:16:30Z',
                        'markets': [
                            {
                                'key': 'h2h',
                                'last_update': '2026-04-24T06:16:30Z',
                                'outcomes': [
                                    {'name': 'Liverpool', 'price': 1.48},
                                    {'name': 'Draw', 'price': 4.40},
                                    {'name': 'Crystal Palace', 'price': 6.10},
                                ],
                            },
                            {
                                'key': 'totals',
                                'last_update': '2026-04-24T06:16:30Z',
                                'outcomes': [
                                    {'name': 'Over', 'price': 1.24, 'point': 1.5},
                                    {'name': 'Over', 'price': 1.61, 'point': 2.5},
                                    {'name': 'Under', 'price': 2.30, 'point': 2.5},
                                ],
                            },
                            {
                                'key': 'btts',
                                'last_update': '2026-04-24T06:16:30Z',
                                'outcomes': [
                                    {'name': 'Yes', 'price': 1.70},
                                    {'name': 'No', 'price': 2.10},
                                ],
                            },
                            {
                                'key': 'spreads',
                                'last_update': '2026-04-24T06:16:30Z',
                                'outcomes': [
                                    {'name': 'Liverpool', 'price': 1.92, 'point': -0.5},
                                    {'name': 'Crystal Palace', 'price': 1.94, 'point': 0.5},
                                    {'name': 'Liverpool', 'price': 2.68, 'point': -2.0},
                                    {'name': 'Crystal Palace', 'price': 1.50, 'point': 2.0},
                                    {'name': 'Liverpool', 'price': 1.55, 'point': 0.25},
                                    {'name': 'Crystal Palace', 'price': 2.55, 'point': -0.25},
                                ],
                            },
                        ],
                    },
                    {
                        'key': 'pinnacle',
                        'title': 'Pinnacle',
                        'last_update': '2026-04-24T06:20:30Z',
                        'markets': [
                            {
                                'key': 'h2h',
                                'last_update': '2026-04-24T06:20:30Z',
                                'outcomes': [
                                    {'name': 'Liverpool', 'price': 1.50},
                                    {'name': 'Draw', 'price': 4.35},
                                    {'name': 'Crystal Palace', 'price': 6.25},
                                ],
                            }
                        ],
                    },
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url='https://example.test', transport=transport)
    event_repository = InMemoryOddsEventRepository()
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=event_repository,
        client=client,
    )

    snapshot = odds_client.fetch_fixture_odds('1234')

    assert snapshot.provider == 'the-odds-api'
    assert snapshot.bookmaker_count == 2
    assert str(snapshot.updated_at) == '2026-04-24 06:20:30+00:00'
    assert set(snapshot.markets) == {
        'match_winner',
        'totals_1_5',
        'totals_2_5',
        'btts',
        'asian_handicap_0_5',
        'asian_handicap_2_0',
        'asian_handicap_0_25',
    }

    match_winner = snapshot.markets['match_winner']
    assert [outcome.outcome_key for outcome in match_winner.outcomes] == [
        'home',
        'draw',
        'away',
    ]
    assert len(match_winner.outcomes[0].bookmaker_quotes) == 2
    assert match_winner.outcomes[0].bookmaker_quotes[0].bookmaker_name == 'Bet365'

    totals = snapshot.markets['totals_2_5']
    assert totals.line == '2.5'
    assert [outcome.outcome_key for outcome in totals.outcomes] == ['over', 'under']

    btts = snapshot.markets['btts']
    assert [outcome.outcome_key for outcome in btts.outcomes] == ['yes', 'no']

    asian = snapshot.markets['asian_handicap_0_5']
    assert asian.line == '0.5'
    assert [outcome.outcome_key for outcome in asian.outcomes] == ['home', 'away']

    strong_asian = snapshot.markets['asian_handicap_2_0']
    assert strong_asian.line == '2.0'
    assert [outcome.outcome_key for outcome in strong_asian.outcomes] == ['home', 'away']

    quarter_asian = snapshot.markets['asian_handicap_0_25']
    assert quarter_asian.line == '0.25'
    assert [outcome.outcome_key for outcome in quarter_asian.outcomes] == ['home', 'away']

    cached_event = event_repository.get_event('1234', provider='the-odds-api')
    assert cached_event is not None
    assert cached_event.event_id == 'event-123'
    assert cached_event.sport_key == 'soccer_epl'


def test_fetch_fixture_odds_reuses_cached_event_mapping() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient
    from nutmeg.domain.odds import OddsProviderEvent

    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        assert request.url.path == '/sports/soccer_epl/events/event-123/odds'
        return httpx.Response(
            200,
            json={
                'id': 'event-123',
                'sport_key': 'soccer_epl',
                'sport_title': 'Premier League',
                'commence_time': '2026-04-25T14:02:00Z',
                'home_team': 'Liverpool',
                'away_team': 'Crystal Palace',
                'bookmakers': [],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url='https://example.test', transport=transport)
    event_repository = InMemoryOddsEventRepository()
    event_repository.upsert_event(
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
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=event_repository,
        client=client,
    )

    snapshot = odds_client.fetch_fixture_odds('1234')

    assert snapshot.provider == 'the-odds-api'
    assert seen_paths == ['/sports/soccer_epl/events/event-123/odds']


def test_fetch_fixture_odds_refreshes_stale_cached_event_mapping() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient
    from nutmeg.domain.odds import OddsProviderEvent

    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == '/sports/soccer_epl/events/stale-event/odds':
            return httpx.Response(404, json={'message': 'event not found'})
        if request.url.path == '/sports/soccer_epl/events':
            return httpx.Response(
                200,
                json=[
                    {
                        'id': 'event-456',
                        'sport_key': 'soccer_epl',
                        'sport_title': 'Premier League',
                        'commence_time': '2026-04-25T14:02:00Z',
                        'home_team': 'Liverpool',
                        'away_team': 'Crystal Palace',
                    }
                ],
            )
        assert request.url.path == '/sports/soccer_epl/events/event-456/odds'
        return httpx.Response(
            200,
            json={
                'id': 'event-456',
                'sport_key': 'soccer_epl',
                'sport_title': 'Premier League',
                'commence_time': '2026-04-25T14:02:00Z',
                'home_team': 'Liverpool',
                'away_team': 'Crystal Palace',
                'bookmakers': [
                    {
                        'key': 'bet365',
                        'title': 'Bet365',
                        'last_update': '2026-04-24T06:16:30Z',
                        'markets': [
                            {
                                'key': 'h2h',
                                'last_update': '2026-04-24T06:16:30Z',
                                'outcomes': [
                                    {'name': 'Liverpool', 'price': 1.48},
                                    {'name': 'Draw', 'price': 4.40},
                                    {'name': 'Crystal Palace', 'price': 6.10},
                                ],
                            }
                        ],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url='https://example.test', transport=transport)
    event_repository = InMemoryOddsEventRepository()
    event_repository.upsert_event(
        OddsProviderEvent(
            fixture_id='1234',
            provider='the-odds-api',
            sport_key='soccer_epl',
            event_id='stale-event',
            home_team='Liverpool',
            away_team='Crystal Palace',
            commence_time=datetime(2026, 4, 25, 14, 2, tzinfo=UTC),
            matched_at=datetime(2026, 4, 24, 6, 0, tzinfo=UTC),
        )
    )
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=event_repository,
        client=client,
    )

    snapshot = odds_client.fetch_fixture_odds('1234')

    assert snapshot.provider == 'the-odds-api'
    assert set(snapshot.markets) == {'match_winner'}
    assert seen_paths == [
        '/sports/soccer_epl/events/stale-event/odds',
        '/sports/soccer_epl/events',
        '/sports/soccer_epl/events/event-456/odds',
    ]
    refreshed_event = event_repository.get_event('1234', provider='the-odds-api')
    assert refreshed_event is not None
    assert refreshed_event.event_id == 'event-456'


def test_fetch_fixture_odds_reports_stale_cache_when_recovery_cannot_reconcile() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient, TheOddsApiError
    from nutmeg.domain.odds import OddsProviderEvent

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/sports/soccer_epl/events/stale-event/odds':
            return httpx.Response(404, json={'message': 'event not found'})
        assert request.url.path == '/sports/soccer_epl/events'
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url='https://example.test', transport=transport)
    event_repository = InMemoryOddsEventRepository()
    event_repository.upsert_event(
        OddsProviderEvent(
            fixture_id='1234',
            provider='the-odds-api',
            sport_key='soccer_epl',
            event_id='stale-event',
            home_team='Liverpool',
            away_team='Crystal Palace',
            commence_time=datetime(2026, 4, 25, 14, 2, tzinfo=UTC),
            matched_at=datetime(2026, 4, 24, 6, 0, tzinfo=UTC),
        )
    )
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=event_repository,
        client=client,
    )

    with pytest.raises(TheOddsApiError, match='Cached The Odds API event `stale-event`'):
        odds_client.fetch_fixture_odds('1234')

    assert event_repository.get_event('1234', provider='the-odds-api') is None


def test_fetch_fixture_odds_fails_truthfully_when_event_cannot_be_reconciled() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient, TheOddsApiError

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    'id': 'event-999',
                    'sport_key': 'soccer_epl',
                    'sport_title': 'Premier League',
                    'commence_time': '2026-04-26T14:00:00Z',
                    'home_team': 'Liverpool',
                    'away_team': 'Everton',
                }
            ],
        )
    )
    client = httpx.Client(base_url='https://example.test', transport=transport)
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=InMemoryOddsEventRepository(),
        client=client,
    )

    with pytest.raises(TheOddsApiError, match='fixture-to-event reconciliation failed'):
        odds_client.fetch_fixture_odds('1234')

def test_the_odds_api_health_snapshot_tracks_cache_miss_reconciliation() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient

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
        assert request.url.path == '/sports/soccer_epl/events/event-123/odds'
        return httpx.Response(
            200,
            json={
                'id': 'event-123',
                'home_team': 'Liverpool',
                'away_team': 'Crystal Palace',
                'bookmakers': [],
            },
        )

    client = httpx.Client(base_url='https://example.test', transport=httpx.MockTransport(handler))
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=InMemoryOddsEventRepository(),
        client=client,
    )

    snapshot = odds_client.fetch_fixture_odds('1234')
    health = odds_client.health_snapshot()

    assert snapshot.provider == 'the-odds-api'
    assert health.provider == 'the-odds-api'
    assert health.cache_hits == 0
    assert health.cache_misses == 1
    assert health.reconcile_attempts == 1
    assert health.reconcile_failures == 0
    assert health.last_event_id == 'event-123'
    assert health.last_error is None
    assert not hasattr(snapshot.provider, 'health')


def test_the_odds_api_health_snapshot_tracks_cache_hit() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient
    from nutmeg.domain.odds import OddsProviderEvent

    event_repository = InMemoryOddsEventRepository()
    event_repository.upsert_event(
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

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == '/sports/soccer_epl/events/event-123/odds'
        return httpx.Response(
            200,
            json={
                'home_team': 'Liverpool',
                'away_team': 'Crystal Palace',
                'bookmakers': [],
            },
        )

    client = httpx.Client(base_url='https://example.test', transport=httpx.MockTransport(handler))
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=event_repository,
        client=client,
    )

    odds_client.fetch_fixture_odds('1234')
    health = odds_client.health_snapshot()

    assert health.cache_hits == 1
    assert health.cache_misses == 0
    assert health.reconcile_attempts == 0
    assert health.last_event_id == 'event-123'


def test_the_odds_api_health_snapshot_tracks_stale_refresh_success() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient
    from nutmeg.domain.odds import OddsProviderEvent

    event_repository = InMemoryOddsEventRepository()
    event_repository.upsert_event(
        OddsProviderEvent(
            fixture_id='1234',
            provider='the-odds-api',
            sport_key='soccer_epl',
            event_id='stale-event',
            home_team='Liverpool',
            away_team='Crystal Palace',
            commence_time=datetime(2026, 4, 25, 14, 2, tzinfo=UTC),
            matched_at=datetime(2026, 4, 24, 6, 0, tzinfo=UTC),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/sports/soccer_epl/events/stale-event/odds':
            return httpx.Response(404, json={'message': 'event not found'})
        if request.url.path == '/sports/soccer_epl/events':
            return httpx.Response(
                200,
                json=[
                    {
                        'id': 'event-456',
                        'commence_time': '2026-04-25T14:02:00Z',
                        'home_team': 'Liverpool',
                        'away_team': 'Crystal Palace',
                    }
                ],
            )
        assert request.url.path == '/sports/soccer_epl/events/event-456/odds'
        return httpx.Response(
            200,
            json={
                'home_team': 'Liverpool',
                'away_team': 'Crystal Palace',
                'bookmakers': [],
            },
        )

    client = httpx.Client(base_url='https://example.test', transport=httpx.MockTransport(handler))
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=event_repository,
        client=client,
    )

    odds_client.fetch_fixture_odds('1234')
    health = odds_client.health_snapshot()

    assert health.cache_hits == 1
    assert health.stale_refresh_attempts == 1
    assert health.stale_refresh_successes == 1
    assert health.reconcile_attempts == 1
    assert health.last_event_id == 'event-456'
    assert health.last_error is None


def test_the_odds_api_health_snapshot_tracks_stale_refresh_failure() -> None:
    from nutmeg.data.the_odds_api import TheOddsApiClient, TheOddsApiError
    from nutmeg.domain.odds import OddsProviderEvent

    event_repository = InMemoryOddsEventRepository()
    event_repository.upsert_event(
        OddsProviderEvent(
            fixture_id='1234',
            provider='the-odds-api',
            sport_key='soccer_epl',
            event_id='stale-event',
            home_team='Liverpool',
            away_team='Crystal Palace',
            commence_time=datetime(2026, 4, 25, 14, 2, tzinfo=UTC),
            matched_at=datetime(2026, 4, 24, 6, 0, tzinfo=UTC),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/sports/soccer_epl/events/stale-event/odds':
            return httpx.Response(404, json={'message': 'event not found'})
        return httpx.Response(200, json=[])

    client = httpx.Client(base_url='https://example.test', transport=httpx.MockTransport(handler))
    odds_client = TheOddsApiClient(
        base_url='https://example.test',
        api_key='demo-key',
        fixture_repository=FakeFixtureRepository(_fixture()),
        event_repository=event_repository,
        client=client,
    )

    with pytest.raises(TheOddsApiError):
        odds_client.fetch_fixture_odds('1234')
    health = odds_client.health_snapshot()

    assert health.stale_refresh_attempts == 1
    assert health.stale_refresh_successes == 0
    assert health.reconcile_failures == 1
    assert health.last_error is not None
    assert 'replacement reconciliation failed' in health.last_error
