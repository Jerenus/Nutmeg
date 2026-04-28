from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from nutmeg.config.settings import AppSettings
from nutmeg.storage.duckdb_utils import connect_analytics_db
from nutmeg.storage.state_models import Base


def ensure_storage_paths(settings: AppSettings) -> None:
    for path in (settings.data_dir, settings.state_dir, settings.analytics_dir):
        Path(path).mkdir(parents=True, exist_ok=True)


def build_state_engine(settings: AppSettings) -> Engine:
    ensure_storage_paths(settings)
    return create_engine(settings.state_db_url, future=True)


def create_state_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def create_analytics_schema(settings: AppSettings) -> None:
    ensure_storage_paths(settings)
    with connect_analytics_db(settings.analytics_db_path) as connection:
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS fixtures (
                fixture_id VARCHAR PRIMARY KEY,
                league_code VARCHAR NOT NULL,
                provider_league_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                kickoff_at TIMESTAMP NOT NULL,
                home_team_id INTEGER,
                away_team_id INTEGER,
                home_team VARCHAR NOT NULL,
                away_team VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                status_short VARCHAR NOT NULL,
                status_long VARCHAR NOT NULL,
                round_name VARCHAR,
                venue VARCHAR,
                referee VARCHAR,
                home_goals INTEGER,
                away_goals INTEGER,
                updated_at TIMESTAMP NOT NULL
            )
            '''
        )
        connection.execute(
            'CREATE INDEX IF NOT EXISTS idx_fixtures_league_kickoff '
            'ON fixtures (league_code, kickoff_at)'
        )
        connection.execute('ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS home_team_id INTEGER')
        connection.execute('ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS away_team_id INTEGER')
        connection.execute('ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS referee VARCHAR')
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS player_identity_map (
                identity_id VARCHAR PRIMARY KEY,
                league_code VARCHAR NOT NULL,
                team_name VARCHAR NOT NULL,
                canonical_name VARCHAR NOT NULL,
                normalized_name VARCHAR NOT NULL,
                position_group VARCHAR,
                updated_at TIMESTAMP NOT NULL
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS player_identity_aliases (
                identity_id VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                alias_name VARCHAR NOT NULL,
                normalized_alias VARCHAR NOT NULL,
                provider_player_id VARCHAR,
                position_group VARCHAR,
                confidence VARCHAR NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            '''
        )
        connection.execute(
            'CREATE INDEX IF NOT EXISTS idx_player_alias_lookup '
            'ON player_identity_aliases (provider, normalized_alias)'
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS venue_reference (
                venue_key VARCHAR PRIMARY KEY,
                venue_name VARCHAR NOT NULL,
                country_name VARCHAR,
                latitude DOUBLE NOT NULL,
                longitude DOUBLE NOT NULL,
                timezone VARCHAR,
                source VARCHAR NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS weather_cache (
                weather_key VARCHAR PRIMARY KEY,
                venue_key VARCHAR NOT NULL,
                kickoff_at TIMESTAMP NOT NULL,
                temperature_c DOUBLE,
                precipitation_probability INTEGER,
                wind_speed_kph DOUBLE,
                weather_code INTEGER,
                source VARCHAR NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS tm_clubs_cache (
                club_id BIGINT,
                name VARCHAR,
                domestic_competition_id VARCHAR
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS tm_players_cache (
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
            CREATE TABLE IF NOT EXISTS tm_games_cache (
                game_id BIGINT,
                date DATE,
                home_club_id BIGINT,
                away_club_id BIGINT,
                home_club_formation VARCHAR,
                away_club_formation VARCHAR
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS sd_team_season_cache (
                league_code VARCHAR,
                season INTEGER,
                team_name VARCHAR,
                matches DOUBLE,
                goals DOUBLE,
                shots DOUBLE,
                shots_on_target DOUBLE,
                xg DOUBLE,
                non_penalty_xg DOUBLE
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS sd_team_match_cache (
                league_code VARCHAR,
                season INTEGER,
                team_name VARCHAR,
                game_id BIGINT,
                date TIMESTAMP,
                points INTEGER,
                expected_points DOUBLE,
                goals_for DOUBLE,
                goals_against DOUBLE,
                xg_for DOUBLE,
                xg_against DOUBLE
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS sd_team_shot_cache (
                league_code VARCHAR,
                season INTEGER,
                team_name VARCHAR,
                game_id BIGINT,
                shots INTEGER,
                goals INTEGER,
                total_xg DOUBLE,
                open_play_shots INTEGER
            )
            '''
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS sd_player_season_cache (
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
            CREATE TABLE IF NOT EXISTS player_availability_cache (
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
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS odds_market_history (
                fixture_id VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                captured_at TIMESTAMP NOT NULL,
                market_key VARCHAR NOT NULL,
                line VARCHAR,
                bookmaker_count INTEGER NOT NULL,
                outcome_key VARCHAR NOT NULL,
                fair_probability DOUBLE,
                fair_odds DOUBLE,
                best_odds DOUBLE
            )
            '''
        )
        connection.execute(
            'CREATE INDEX IF NOT EXISTS idx_odds_history_fixture_market '
            'ON odds_market_history (fixture_id, market_key, captured_at)'
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS odds_provider_events (
                fixture_id VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                sport_key VARCHAR NOT NULL,
                event_id VARCHAR NOT NULL,
                home_team VARCHAR NOT NULL,
                away_team VARCHAR NOT NULL,
                commence_time TIMESTAMP NOT NULL,
                matched_at TIMESTAMP NOT NULL,
                PRIMARY KEY (fixture_id, provider)
            )
            '''
        )
        connection.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_odds_provider_events_lookup '
            'ON odds_provider_events (provider, sport_key, event_id)'
        )
        connection.execute(
            '''
            CREATE TABLE IF NOT EXISTS odds_provider_health (
                provider VARCHAR PRIMARY KEY,
                cache_hits INTEGER NOT NULL,
                cache_misses INTEGER NOT NULL,
                reconcile_attempts INTEGER NOT NULL,
                reconcile_failures INTEGER NOT NULL,
                stale_refresh_attempts INTEGER NOT NULL,
                stale_refresh_successes INTEGER NOT NULL,
                last_event_id VARCHAR,
                last_error VARCHAR,
                updated_at TIMESTAMP NOT NULL
            )
            '''
        )
