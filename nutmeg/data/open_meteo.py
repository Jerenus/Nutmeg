from __future__ import annotations

from datetime import UTC
from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from nutmeg.config.catalog import get_league
from nutmeg.config.team_catalog import TeamCatalog, load_team_catalog
from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.snapshot import TravelContext, VenueReference, WeatherContext
from nutmeg.storage.reference_repository import DuckDbReferenceRepository


class OpenMeteoError(RuntimeError):
    pass


def _normalize_location_token(value: str | None) -> str:
    return ' '.join(str(value or '').strip().casefold().split())


class OpenMeteoClient:
    def __init__(
        self,
        *,
        geocoding_base_url: str,
        weather_base_url: str,
        reference_repository: DuckDbReferenceRepository,
        team_catalog: TeamCatalog | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._geocoding_base_url = geocoding_base_url.rstrip('/')
        self._weather_base_url = weather_base_url.rstrip('/')
        self._reference_repository = reference_repository
        self._team_catalog = team_catalog or load_team_catalog()
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=20.0)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_fixture_weather(self, fixture: Fixture) -> WeatherContext | None:
        if fixture.venue is None:
            return None

        league = get_league(fixture.league_code)
        venue = self._get_or_create_venue_reference(
            fixture.venue,
            league.country,
        )
        if venue is None:
            return None

        cached_weather = self._reference_repository.get_weather_cache(
            venue.venue_key,
            fixture.kickoff_at,
        )
        if cached_weather is not None:
            return cached_weather

        weather, forecast_timezone = self._fetch_weather(venue, fixture.kickoff_at)
        if forecast_timezone and venue.timezone != forecast_timezone:
            venue = VenueReference(
                venue_key=venue.venue_key,
                venue_name=venue.venue_name,
                country_name=venue.country_name,
                latitude=venue.latitude,
                longitude=venue.longitude,
                timezone=forecast_timezone,
                source=venue.source,
            )
            self._reference_repository.save_venue_reference(venue)
        self._reference_repository.save_weather_cache(venue.venue_key, weather)
        return weather

    def build_away_travel_context(
        self,
        *,
        fixture: Fixture,
        away_team_name: str,
    ) -> TravelContext | None:
        if fixture.venue is None:
            return None

        league = get_league(fixture.league_code)
        destination = self._get_or_create_venue_reference(fixture.venue, league.country)
        if destination is None:
            return None
        home_base_query = self._team_catalog.home_base_query(away_team_name)
        if home_base_query is None:
            return None
        origin = self._get_or_create_venue_reference(
            home_base_query,
            self._team_catalog.home_country(away_team_name) or league.country,
        )
        if origin is None:
            return None
        distance_km = round(
            self._haversine_km(
                origin.latitude,
                origin.longitude,
                destination.latitude,
                destination.longitude,
            ),
            1,
        )
        return TravelContext(
            distance_km=distance_km,
            bucket=self._distance_bucket(distance_km),
            source='open-meteo',
        )

    def _get_or_create_venue_reference(
        self,
        venue_name: str,
        country_name: str | None,
    ) -> VenueReference | None:
        venue_key = self._reference_repository._venue_key(venue_name, country_name)
        venue = self._reference_repository.get_venue_reference(venue_name, country_name)
        if venue is not None and self._venue_reference_matches_country(venue, country_name):
            return venue
        if venue is not None:
            self._reference_repository.delete_weather_cache_for_venue(venue_key)
        venue = self._fetch_venue_reference(venue_name, country_name)
        if venue is None:
            return None
        self._reference_repository.save_venue_reference(venue)
        return venue

    def _fetch_venue_reference(
        self,
        venue_name: str,
        country_name: str | None,
    ) -> VenueReference | None:
        response = self._client.get(
            f'{self._geocoding_base_url}/search',
            params={
                'name': venue_name,
                'count': 1,
                'language': 'en',
                'format': 'json',
            },
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get('results') or []
        if not results:
            return self._fetch_nominatim_reference(venue_name, country_name)
        item = results[0]
        candidate = VenueReference(
            venue_key=self._reference_repository._venue_key(venue_name, country_name),
            venue_name=item.get('name', venue_name),
            country_name=item.get('country', country_name),
            latitude=float(item['latitude']),
            longitude=float(item['longitude']),
            timezone=item.get('timezone'),
            source='open-meteo',
        )
        if not self._venue_reference_matches_country(candidate, country_name):
            return self._fetch_nominatim_reference(venue_name, country_name)
        return candidate

    def _fetch_nominatim_reference(
        self,
        venue_name: str,
        country_name: str | None,
    ) -> VenueReference | None:
        response = self._client.get(
            'https://nominatim.openstreetmap.org/search',
            params={
                'q': venue_name,
                'format': 'jsonv2',
                'limit': 1,
            },
            headers={'User-Agent': 'nutmeg/0.1'},
        )
        response.raise_for_status()
        results = response.json() or []
        if not results:
            return None
        item = results[0]
        display_name = item.get('display_name') or venue_name
        resolved_name = item.get('name') or venue_name
        return VenueReference(
            venue_key=self._reference_repository._venue_key(venue_name, country_name),
            venue_name=resolved_name,
            country_name=country_name or display_name.split(',')[-1].strip() or None,
            latitude=float(item['lat']),
            longitude=float(item['lon']),
            timezone=None,
            source='nominatim',
        )

    def _fetch_weather(
        self,
        venue: VenueReference,
        kickoff_at,
    ) -> tuple[WeatherContext, str | None]:
        kickoff_utc = kickoff_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        response = self._client.get(
            f'{self._weather_base_url}/forecast',
            params={
                'latitude': venue.latitude,
                'longitude': venue.longitude,
                'hourly': 'temperature_2m,precipitation_probability,wind_speed_10m,weather_code',
                'timezone': venue.timezone or 'auto',
                'start_date': kickoff_utc.date().isoformat(),
                'end_date': kickoff_utc.date().isoformat(),
            },
        )
        response.raise_for_status()
        payload = response.json()
        forecast_timezone = payload.get('timezone')
        hourly = payload.get('hourly') or {}
        time_values = hourly.get('time') or []
        candidates = [kickoff_utc.strftime('%Y-%m-%dT%H:00')]
        timezone_name = venue.timezone or forecast_timezone
        if timezone_name:
            try:
                zone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                zone = None
            if zone is not None:
                candidates.insert(
                    0,
                    kickoff_at.astimezone(zone).replace(
                        minute=0,
                        second=0,
                        microsecond=0,
                    ).strftime('%Y-%m-%dT%H:00'),
                )
        index = None
        target = None
        for candidate in candidates:
            if candidate in time_values:
                index = time_values.index(candidate)
                target = candidate
                break
        if index is None or target is None:
            raise OpenMeteoError(
                'No hourly weather entry found for '
                + ' or '.join(candidates)
                + '.'
            )
        return (
            WeatherContext(
                forecast_at=kickoff_utc,
                temperature_c=self._float_value(hourly.get('temperature_2m'), index),
                precipitation_probability=self._int_value(
                    hourly.get('precipitation_probability'),
                    index,
                ),
                wind_speed_kph=self._float_value(hourly.get('wind_speed_10m'), index),
                weather_code=self._int_value(hourly.get('weather_code'), index),
                source='open-meteo',
            ),
            forecast_timezone,
        )

    def _venue_reference_matches_country(
        self,
        venue: VenueReference,
        requested_country: str | None,
    ) -> bool:
        if requested_country is None or venue.country_name is None:
            return True
        normalized_requested = _normalize_location_token(requested_country)
        normalized_actual = _normalize_location_token(venue.country_name)
        if normalized_requested == normalized_actual:
            return True
        if normalized_requested in normalized_actual or normalized_actual in normalized_requested:
            return True
        uk_aliases = {
            'england',
            'scotland',
            'wales',
            'northern ireland',
        }
        if normalized_requested in uk_aliases and normalized_actual in {
            'united kingdom',
            'great britain',
            'united kingdom of great britain and northern ireland',
        }:
            return True
        return False

    def _float_value(self, values, index: int) -> float | None:
        if values is None or index >= len(values) or values[index] is None:
            return None
        return float(values[index])

    def _int_value(self, values, index: int) -> int | None:
        if values is None or index >= len(values) or values[index] is None:
            return None
        return int(values[index])

    def _distance_bucket(self, distance_km: float) -> str:
        if distance_km < 50:
            return 'short-haul'
        if distance_km < 250:
            return 'regional'
        return 'long-haul'

    def _haversine_km(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        radius_km = 6371.0
        lat1_rad = radians(lat1)
        lon1_rad = radians(lon1)
        lat2_rad = radians(lat2)
        lon2_rad = radians(lon2)
        delta_lat = lat2_rad - lat1_rad
        delta_lon = lon2_rad - lon1_rad
        haversine = (
            sin(delta_lat / 2) ** 2
            + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
        )
        return 2 * radius_km * asin(sqrt(haversine))
