from __future__ import annotations

from datetime import UTC, datetime

import httpx

from nutmeg.config.settings import get_settings
from nutmeg.data.open_meteo import OpenMeteoClient
from nutmeg.domain.fixtures import sample_fixtures
from nutmeg.domain.snapshot import VenueReference, WeatherContext
from nutmeg.storage.bootstrap import create_analytics_schema
from nutmeg.storage.reference_repository import DuckDbReferenceRepository


def test_open_meteo_client_reuses_cached_venue_and_weather() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if 'geocoding-api' in str(request.url):
            calls.append('geocode')
            return httpx.Response(
                200,
                json={
                    'results': [
                        {
                            'name': 'Emirates Stadium',
                            'country': 'England',
                            'timezone': 'Europe/London',
                            'latitude': 51.555,
                            'longitude': -0.1086,
                        }
                    ]
                },
            )
        calls.append('forecast')
        return httpx.Response(
            200,
            json={
                'hourly': {
                    'time': ['2026-04-25T09:00'],
                    'temperature_2m': [14.2],
                    'precipitation_probability': [20],
                    'wind_speed_10m': [12.8],
                    'weather_code': [3],
                }
            },
        )

    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbReferenceRepository(settings)
    client = OpenMeteoClient(
        geocoding_base_url='https://geocoding-api.open-meteo.test/v1/',
        weather_base_url='https://api.open-meteo.test/v1/',
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
        ),
        reference_repository=repository,
    )
    fixture = sample_fixtures('epl')[0]
    fixture = type(fixture)(
        fixture_id=fixture.fixture_id,
        league_code=fixture.league_code,
        provider_league_id=fixture.provider_league_id,
        season=fixture.season,
        kickoff_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        home_team_id=fixture.home_team_id,
        away_team_id=fixture.away_team_id,
        home_team=fixture.home_team,
        away_team=fixture.away_team,
        source=fixture.source,
        status=fixture.status,
        status_short=fixture.status_short,
        status_long=fixture.status_long,
        round_name=fixture.round_name,
        venue=fixture.venue,
        home_goals=fixture.home_goals,
        away_goals=fixture.away_goals,
    )

    first = client.get_fixture_weather(fixture)
    second = client.get_fixture_weather(fixture)

    assert first == second
    assert calls == ['geocode', 'forecast']
    assert first is not None
    assert first.temperature_c == 14.2
    assert first.source == 'open-meteo'


def test_open_meteo_client_builds_away_travel_context_from_cached_geocodes() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if 'geocoding-api' not in str(request.url):
            raise AssertionError('travel context should only use geocoding')
        calls.append(str(request.url.params.get('name')))
        name = str(request.url.params.get('name'))
        if 'Emirates Stadium' in name:
            return httpx.Response(
                200,
                json={
                    'results': [
                        {
                            'name': 'Emirates Stadium',
                            'country': 'England',
                            'timezone': 'Europe/London',
                            'latitude': 51.555,
                            'longitude': -0.1086,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                'results': [
                    {
                        'name': 'Tottenham Hotspur Stadium',
                        'country': 'England',
                        'timezone': 'Europe/London',
                        'latitude': 51.6043,
                        'longitude': -0.0664,
                    }
                ]
            },
        )

    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbReferenceRepository(settings)
    client = OpenMeteoClient(
        geocoding_base_url='https://geocoding-api.open-meteo.test/v1/',
        weather_base_url='https://api.open-meteo.test/v1/',
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
        ),
        reference_repository=repository,
    )

    travel = client.build_away_travel_context(
        fixture=sample_fixtures('epl')[0],
        away_team_name='Tottenham Hotspur',
    )

    assert travel is not None
    assert travel.bucket == 'short-haul'
    assert travel.distance_km is not None
    assert travel.distance_km > 0
    assert calls == [
        'Emirates Stadium',
        'Tottenham Hotspur Stadium, London, England',
    ]


def test_open_meteo_client_refreshes_wrong_country_cached_venue_and_weather() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if 'geocoding-api.open-meteo.test' in str(request.url):
            calls.append('open-meteo-geocode')
            return httpx.Response(
                200,
                json={
                    'results': [
                        {
                            'name': 'Anfield',
                            'country': 'Canada',
                            'timezone': 'America/Moncton',
                            'latitude': 46.92708,
                            'longitude': -67.51354,
                        }
                    ]
                },
            )
        if 'nominatim.openstreetmap.org' in str(request.url):
            calls.append('nominatim')
            return httpx.Response(
                200,
                json=[
                    {
                        'name': 'Anfield',
                        'display_name': 'Anfield, Liverpool, England',
                        'lat': '53.4309012',
                        'lon': '-2.9609719',
                    }
                ],
            )
        calls.append('forecast')
        return httpx.Response(
            200,
            json={
                'timezone': 'Europe/London',
                'hourly': {
                    'time': ['2026-04-25T16:00'],
                    'temperature_2m': [11.3],
                    'precipitation_probability': [40],
                    'wind_speed_10m': [17.2],
                    'weather_code': [61],
                },
            },
        )

    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbReferenceRepository(settings)
    repository.save_venue_reference(
        VenueReference(
            venue_key='anfield-england',
            venue_name='Anfield',
            country_name='Canada',
            latitude=46.92708,
            longitude=-67.51354,
            timezone='America/Moncton',
            source='open-meteo',
        )
    )
    repository.save_weather_cache(
        'anfield-england',
        WeatherContext(
            forecast_at=datetime(2026, 4, 25, 15, 0, tzinfo=UTC),
            temperature_c=-5.0,
            precipitation_probability=90,
            wind_speed_kph=55.0,
            weather_code=71,
            source='open-meteo',
        ),
    )
    client = OpenMeteoClient(
        geocoding_base_url='https://geocoding-api.open-meteo.test/v1/',
        weather_base_url='https://api.open-meteo.test/v1/',
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
        ),
        reference_repository=repository,
    )
    fixture = sample_fixtures('epl')[0]
    fixture = type(fixture)(
        fixture_id=fixture.fixture_id,
        league_code=fixture.league_code,
        provider_league_id=fixture.provider_league_id,
        season=fixture.season,
        kickoff_at=datetime(2026, 4, 25, 15, 0, tzinfo=UTC),
        home_team_id=fixture.home_team_id,
        away_team_id=fixture.away_team_id,
        home_team=fixture.home_team,
        away_team=fixture.away_team,
        source=fixture.source,
        status=fixture.status,
        status_short=fixture.status_short,
        status_long=fixture.status_long,
        round_name=fixture.round_name,
        venue='Anfield',
        home_goals=fixture.home_goals,
        away_goals=fixture.away_goals,
    )

    weather = client.get_fixture_weather(fixture)
    venue = repository.get_venue_reference('Anfield', 'England')

    assert weather is not None
    assert weather.temperature_c == 11.3
    assert venue is not None
    assert venue.country_name == 'England'
    assert venue.timezone == 'Europe/London'
    assert calls == ['open-meteo-geocode', 'nominatim', 'forecast']


def test_open_meteo_client_falls_back_to_nominatim_for_stadium_geocoding() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if 'geocoding-api.open-meteo.test' in str(request.url):
            calls.append('open-meteo-geocode')
            return httpx.Response(200, json={'results': []})
        if 'nominatim.openstreetmap.org' in str(request.url):
            calls.append('nominatim')
            return httpx.Response(
                200,
                json=[
                    {
                        'name': 'Emirates Stadium',
                        'display_name': 'Emirates Stadium, London, England',
                        'lat': '51.5550404',
                        'lon': '-0.1083997',
                    }
                ],
            )
        calls.append('forecast')
        return httpx.Response(
            200,
            json={
                'timezone': 'Europe/London',
                'hourly': {
                    'time': ['2026-04-25T09:00'],
                    'temperature_2m': [14.2],
                    'precipitation_probability': [20],
                    'wind_speed_10m': [12.8],
                    'weather_code': [3],
                },
            },
        )

    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbReferenceRepository(settings)
    client = OpenMeteoClient(
        geocoding_base_url='https://geocoding-api.open-meteo.test/v1/',
        weather_base_url='https://api.open-meteo.test/v1/',
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
        ),
        reference_repository=repository,
    )
    fixture = sample_fixtures('epl')[0]
    fixture = type(fixture)(
        fixture_id=fixture.fixture_id,
        league_code=fixture.league_code,
        provider_league_id=fixture.provider_league_id,
        season=fixture.season,
        kickoff_at=datetime(2026, 4, 25, 8, 0, tzinfo=UTC),
        home_team_id=fixture.home_team_id,
        away_team_id=fixture.away_team_id,
        home_team=fixture.home_team,
        away_team=fixture.away_team,
        source=fixture.source,
        status=fixture.status,
        status_short=fixture.status_short,
        status_long=fixture.status_long,
        round_name=fixture.round_name,
        venue=fixture.venue,
        home_goals=fixture.home_goals,
        away_goals=fixture.away_goals,
    )

    weather = client.get_fixture_weather(fixture)
    venue = repository.get_venue_reference('Emirates Stadium', 'England')

    assert weather is not None
    assert weather.temperature_c == 14.2
    assert venue is not None
    assert venue.timezone == 'Europe/London'
    assert calls == ['open-meteo-geocode', 'nominatim', 'forecast']
