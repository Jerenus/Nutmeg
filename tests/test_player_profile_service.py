from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from nutmeg.domain.players import PlayerProfileUnavailable
from nutmeg.services.players import PlayerProfileService


@dataclass(slots=True, frozen=True)
class ResolvedIdentity:
    identity_id: str
    canonical_name: str
    match_confidence: str


class FakeReferenceRepository:
    def resolve_player_identity(
        self,
        *,
        league_code: str,
        team_name: str,
        provider: str,
        player_name: str,
        position: str | None = None,
        provider_player_id: str | None = None,
    ):
        assert league_code == 'epl'
        assert team_name == 'Arsenal'
        assert provider == 'player-profile'
        if player_name in {'Bukayo Saka', 'B. Saka'}:
            return ResolvedIdentity(
                identity_id='epl:arsenal:bukayo-saka',
                canonical_name='Bukayo Saka',
                match_confidence='catalog',
            )
        return None


def _seed_player_cache(db_path) -> None:
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            '''
            CREATE TABLE tm_clubs_cache (
                club_id BIGINT,
                name VARCHAR,
                domestic_competition_id VARCHAR
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE tm_players_cache (
                player_id BIGINT,
                name VARCHAR,
                current_club_id BIGINT,
                position VARCHAR,
                market_value_in_eur BIGINT
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE sd_player_season_cache (
                league_code VARCHAR,
                season INTEGER,
                team_name VARCHAR,
                player_name VARCHAR,
                position VARCHAR,
                minutes DOUBLE,
                goals_per90 DOUBLE,
                assists_per90 DOUBLE,
                xg_per90 DOUBLE,
                xa_per90 DOUBLE,
                key_passes_per90 DOUBLE,
                duels_won_per90 DOUBLE
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE player_availability_cache (
                league_code VARCHAR,
                team_name VARCHAR,
                player_name VARCHAR,
                status VARCHAR,
                reason VARCHAR,
                expected_return VARCHAR,
                source VARCHAR,
                updated_at TIMESTAMP
            )
            '''
        )
        connection.executemany(
            'INSERT INTO tm_clubs_cache VALUES (?, ?, ?)',
            [
                (11, 'Arsenal Football Club', 'GB1'),
                (22, 'Manchester City Football Club', 'GB1'),
            ],
        )
        connection.executemany(
            'INSERT INTO tm_players_cache VALUES (?, ?, ?, ?, ?)',
            [
                (7, 'Bukayo Saka', 11, 'Right Winger', 140_000_000),
                (47, 'Phil Foden', 22, 'Right Winger', 130_000_000),
            ],
        )
        connection.executemany(
            'INSERT INTO sd_player_season_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                (
                    'epl',
                    2025,
                    'Arsenal',
                    'Bukayo Saka',
                    'Right Winger',
                    2500,
                    0.42,
                    0.33,
                    0.48,
                    0.30,
                    2.4,
                    3.2,
                ),
                (
                    'epl',
                    2025,
                    'Manchester City',
                    'Phil Foden',
                    'Right Winger',
                    2300,
                    0.39,
                    0.31,
                    0.45,
                    0.29,
                    2.2,
                    3.0,
                ),
                (
                    'epl',
                    2025,
                    'Arsenal',
                    'William Saliba',
                    'Centre-Back',
                    2700,
                    0.05,
                    0.02,
                    0.04,
                    0.01,
                    0.3,
                    5.8,
                ),
            ],
        )
        connection.execute(
            'INSERT INTO player_availability_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            [
                'epl',
                'Arsenal',
                'Bukayo Saka',
                'available',
                None,
                None,
                'local-cache',
                datetime(2026, 4, 25, 9, 0, tzinfo=UTC).replace(tzinfo=None),
            ],
        )


def test_player_profile_aggregates_identity_market_metrics_and_similarity(tmp_path) -> None:
    db_path = tmp_path / 'analytics.duckdb'
    _seed_player_cache(db_path)
    service = PlayerProfileService(
        database_path=db_path,
        reference_repository=FakeReferenceRepository(),
    )

    profile = service.build_profile(
        league='epl',
        season=2025,
        team='Arsenal',
        player='B. Saka',
        similar_limit=2,
    )

    assert profile.identity is not None
    assert profile.identity.canonical_name == 'Bukayo Saka'
    assert profile.identity.match_confidence == 'catalog'
    assert profile.market is not None
    assert profile.market.market_value_eur == 140_000_000
    assert profile.market.position == 'Right Winger'
    assert profile.season_metrics is not None
    assert profile.season_metrics.xg_per90 == 0.48
    assert profile.availability is not None
    assert profile.availability.status == 'available'
    assert profile.similar_players
    assert profile.similar_players[0].player_name == 'Phil Foden'
    assert profile.similar_players[0].similarity_score > 0.95
    assert profile.unavailable_sections == []


def test_player_profile_marks_missing_sections_truthfully(tmp_path) -> None:
    db_path = tmp_path / 'analytics.duckdb'
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            '''
            CREATE TABLE tm_clubs_cache (
                club_id BIGINT,
                name VARCHAR,
                domestic_competition_id VARCHAR
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE tm_players_cache (
                player_id BIGINT,
                name VARCHAR,
                current_club_id BIGINT,
                position VARCHAR,
                market_value_in_eur BIGINT
            )
            '''
        )

    service = PlayerProfileService(
        database_path=db_path,
        reference_repository=FakeReferenceRepository(),
    )

    profile = service.build_profile(
        league='epl',
        season=2025,
        team='Arsenal',
        player='Mystery Trialist',
    )

    assert profile.identity is None
    assert PlayerProfileUnavailable.IDENTITY in profile.unavailable_sections
    assert PlayerProfileUnavailable.MARKET in profile.unavailable_sections
    assert PlayerProfileUnavailable.SEASON_METRICS in profile.unavailable_sections
    assert PlayerProfileUnavailable.AVAILABILITY in profile.unavailable_sections
    assert PlayerProfileUnavailable.SIMILAR_PLAYERS in profile.unavailable_sections
