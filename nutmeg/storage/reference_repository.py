from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from nutmeg.config.settings import AppSettings
from nutmeg.domain.snapshot import VenueReference, WeatherContext
from nutmeg.storage.duckdb_utils import connect_analytics_db


@dataclass(slots=True, frozen=True)
class ResolvedPlayerIdentity:
    identity_id: str
    canonical_name: str
    match_confidence: str


@dataclass(slots=True, frozen=True)
class PlayerAliasEntry:
    canonical_name: str
    aliases: tuple[str, ...]
    position_group: str | None = None


class PlayerAliasCatalog:
    def __init__(self, entries: dict[str, dict[str, PlayerAliasEntry]]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, config_path: str = 'config/player_aliases.yaml') -> 'PlayerAliasCatalog':
        path = Path(config_path)
        payload = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
        teams: dict[str, dict[str, PlayerAliasEntry]] = {}
        for team_name, players in (payload or {}).get('players', {}).items():
            team_entries: dict[str, PlayerAliasEntry] = {}
            for canonical_name, item in players.items():
                team_entries[canonical_name] = PlayerAliasEntry(
                    canonical_name=canonical_name,
                    aliases=tuple(item.get('aliases', [])),
                    position_group=item.get('position_group'),
                )
            teams[team_name] = team_entries
        return cls(teams)

    def resolve(self, team_name: str, player_name: str) -> PlayerAliasEntry | None:
        normalized = normalize_person_name(player_name)
        for entry in self._entries.get(team_name, {}).values():
            if normalize_person_name(entry.canonical_name) == normalized:
                return entry
            for alias in entry.aliases:
                if normalize_person_name(alias) == normalized:
                    return entry
        return None


def normalize_person_name(value: str) -> str:
    ascii_value = (
        unicodedata.normalize('NFKD', value)
        .encode('ascii', 'ignore')
        .decode('ascii')
    )
    return re.sub(r'[^a-z0-9]+', ' ', ascii_value.lower()).strip()


def _slug(value: str) -> str:
    return normalize_person_name(value).replace(' ', '-')


class DuckDbReferenceRepository:
    def __init__(
        self,
        settings: AppSettings,
        *,
        player_aliases_path: str = 'config/player_aliases.yaml',
    ) -> None:
        self._db_path = settings.analytics_db_path
        self._alias_catalog = PlayerAliasCatalog.load(player_aliases_path)

    def resolve_player_identity(
        self,
        *,
        league_code: str,
        team_name: str,
        provider: str,
        player_name: str,
        position: str | None = None,
        provider_player_id: str | None = None,
    ) -> ResolvedPlayerIdentity | None:
        normalized_name = normalize_person_name(player_name)
        alias_entry = self._alias_catalog.resolve(team_name, player_name)
        canonical_name = alias_entry.canonical_name if alias_entry else player_name
        normalized_canonical = normalize_person_name(canonical_name)
        position_group = alias_entry.position_group if alias_entry else position
        now = datetime.now(UTC).replace(tzinfo=None)

        with connect_analytics_db(self._db_path) as connection:
            if provider_player_id is not None:
                row = connection.execute(
                    '''
                    SELECT pim.identity_id, pim.canonical_name, pia.confidence
                    FROM player_identity_aliases pia
                    JOIN player_identity_map pim ON pim.identity_id = pia.identity_id
                    WHERE pim.league_code = ?
                      AND pim.team_name = ?
                      AND pia.provider = ?
                      AND pia.provider_player_id = ?
                    LIMIT 1
                    ''',
                    [league_code, team_name, provider, provider_player_id],
                ).fetchone()
                if row is not None:
                    return ResolvedPlayerIdentity(row[0], row[1], row[2])

            row = connection.execute(
                '''
                SELECT pim.identity_id, pim.canonical_name, pia.confidence
                FROM player_identity_aliases pia
                JOIN player_identity_map pim ON pim.identity_id = pia.identity_id
                WHERE pim.league_code = ?
                  AND pim.team_name = ?
                  AND pia.normalized_alias = ?
                LIMIT 1
                ''',
                [league_code, team_name, normalized_name],
            ).fetchone()
            if row is not None:
                return ResolvedPlayerIdentity(row[0], row[1], row[2])

            row = connection.execute(
                '''
                SELECT identity_id, canonical_name
                FROM player_identity_map
                WHERE league_code = ?
                  AND team_name = ?
                  AND normalized_name = ?
                LIMIT 1
                ''',
                [league_code, team_name, normalized_canonical],
            ).fetchone()
            if row is None and alias_entry is None and provider_player_id is None:
                return None

            if row is None:
                identity_id = f'{league_code}:{_slug(team_name)}:{_slug(canonical_name)}'
                connection.execute(
                    '''
                    INSERT INTO player_identity_map (
                        identity_id,
                        league_code,
                        team_name,
                        canonical_name,
                        normalized_name,
                        position_group,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        identity_id,
                        league_code,
                        team_name,
                        canonical_name,
                        normalized_canonical,
                        position_group,
                        now,
                    ],
                )
            else:
                identity_id = row[0]
                canonical_name = row[1]

            confidence = (
                'catalog'
                if alias_entry and normalized_name != normalized_canonical
                else 'normalized'
            )
            connection.execute(
                '''
                INSERT INTO player_identity_aliases (
                    identity_id,
                    provider,
                    alias_name,
                    normalized_alias,
                    provider_player_id,
                    position_group,
                    confidence,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    identity_id,
                    provider,
                    player_name,
                    normalized_name,
                    provider_player_id,
                    position_group,
                    confidence,
                    now,
                ],
            )
        return ResolvedPlayerIdentity(identity_id, canonical_name, confidence)

    def get_venue_reference(
        self,
        venue_name: str,
        country_name: str | None = None,
    ) -> VenueReference | None:
        with connect_analytics_db(self._db_path) as connection:
            row = connection.execute(
                '''
                SELECT venue_key, venue_name, country_name, latitude, longitude, timezone, source
                FROM venue_reference
                WHERE venue_key = ?
                LIMIT 1
                ''',
                [self._venue_key(venue_name, country_name)],
            ).fetchone()
        if row is None:
            return None
        return VenueReference(
            venue_key=row[0],
            venue_name=row[1],
            country_name=row[2],
            latitude=float(row[3]),
            longitude=float(row[4]),
            timezone=row[5],
            source=row[6],
        )

    def save_venue_reference(self, reference: VenueReference) -> VenueReference:
        now = datetime.now(UTC).replace(tzinfo=None)
        with connect_analytics_db(self._db_path) as connection:
            connection.execute(
                'DELETE FROM venue_reference WHERE venue_key = ?',
                [reference.venue_key],
            )
            connection.execute(
                '''
                INSERT INTO venue_reference (
                    venue_key,
                    venue_name,
                    country_name,
                    latitude,
                    longitude,
                    timezone,
                    source,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    reference.venue_key,
                    reference.venue_name,
                    reference.country_name,
                    reference.latitude,
                    reference.longitude,
                    reference.timezone,
                    reference.source,
                    now,
                ],
            )
        return reference

    def get_weather_cache(self, venue_key: str, kickoff_at: datetime) -> WeatherContext | None:
        with connect_analytics_db(self._db_path) as connection:
            row = connection.execute(
                '''
                SELECT
                    kickoff_at,
                    temperature_c,
                    precipitation_probability,
                    wind_speed_kph,
                    weather_code,
                    source
                FROM weather_cache
                WHERE weather_key = ?
                LIMIT 1
                ''',
                [self._weather_key(venue_key, kickoff_at)],
            ).fetchone()
        if row is None:
            return None
        return WeatherContext(
            forecast_at=row[0].replace(tzinfo=UTC),
            temperature_c=float(row[1]) if row[1] is not None else None,
            precipitation_probability=int(row[2]) if row[2] is not None else None,
            wind_speed_kph=float(row[3]) if row[3] is not None else None,
            weather_code=int(row[4]) if row[4] is not None else None,
            source=row[5],
        )

    def save_weather_cache(self, venue_key: str, weather: WeatherContext) -> WeatherContext:
        now = datetime.now(UTC).replace(tzinfo=None)
        with connect_analytics_db(self._db_path) as connection:
            connection.execute(
                'DELETE FROM weather_cache WHERE weather_key = ?',
                [self._weather_key(venue_key, weather.forecast_at)],
            )
            connection.execute(
                '''
                INSERT INTO weather_cache (
                    weather_key,
                    venue_key,
                    kickoff_at,
                    temperature_c,
                    precipitation_probability,
                    wind_speed_kph,
                    weather_code,
                    source,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    self._weather_key(venue_key, weather.forecast_at),
                    venue_key,
                    weather.forecast_at.astimezone(UTC).replace(tzinfo=None),
                    weather.temperature_c,
                    weather.precipitation_probability,
                    weather.wind_speed_kph,
                    weather.weather_code,
                    weather.source,
                    now,
                ],
            )
        return weather

    def delete_weather_cache_for_venue(self, venue_key: str) -> None:
        with connect_analytics_db(self._db_path) as connection:
            connection.execute(
                'DELETE FROM weather_cache WHERE venue_key = ?',
                [venue_key],
            )

    def _venue_key(self, venue_name: str, country_name: str | None = None) -> str:
        suffix = f'-{_slug(country_name)}' if country_name else ''
        return f'{_slug(venue_name)}{suffix}'

    def _weather_key(self, venue_key: str, kickoff_at: datetime) -> str:
        normalized_kickoff = kickoff_at.astimezone(UTC).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        return f'{venue_key}:{normalized_kickoff.isoformat()}'
