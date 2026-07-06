from __future__ import annotations

import duckdb

from nutmeg.config.team_catalog import load_team_catalog
from nutmeg.data.soccerdata_client import SoccerDataClient
from nutmeg.data.transfermarkt import TransfermarktDataset
from nutmeg.domain.fixtures import sample_fixtures


class ExplodingSoccerDataBackend:
    def build_fbref_reader(self, **kwargs: object):
        raise AssertionError('live fbref backend should not be called')

    def build_understat_reader(self, **kwargs: object):
        raise AssertionError('live understat backend should not be called')


def test_transfermarkt_dataset_reads_local_materialized_cache(tmp_path) -> None:
    db_path = tmp_path / 'analytics.duckdb'
    con = duckdb.connect(str(db_path))
    con.execute(
        '''
        CREATE TABLE tm_clubs_cache (
            club_id BIGINT,
            name VARCHAR,
            domestic_competition_id VARCHAR
        )
        '''
    )
    con.execute(
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
    con.execute(
        '''
        CREATE TABLE tm_games_cache (
            game_id BIGINT,
            date DATE,
            home_club_id BIGINT,
            away_club_id BIGINT,
            home_club_formation VARCHAR,
            away_club_formation VARCHAR
        )
        '''
    )
    con.executemany(
        'INSERT INTO tm_clubs_cache VALUES (?, ?, ?)',
        [(11, 'Arsenal Football Club', 'GB1')],
    )
    con.executemany(
        'INSERT INTO tm_players_cache VALUES (?, ?, ?, ?, ?)',
        [
            (1, 'David Raya', 11, 'Goalkeeper', 32000000),
            (2, 'William Saliba', 11, 'Defender', 80000000),
            (3, 'Declan Rice', 11, 'Midfielder', 110000000),
            (4, 'Bukayo Saka', 11, 'Attack', 140000000),
        ],
    )
    con.executemany(
        'INSERT INTO tm_games_cache VALUES (?, ?, ?, ?, ?, ?)',
        [(1001, '2026-04-01', 11, 31, '4-3-3', '4-3-3')],
    )
    con.close()

    dataset = TransfermarktDataset(
        database_path=db_path,
        team_catalog=load_team_catalog(),
    )

    market_value = dataset.fetch_team_market_value(league_code='epl', team_name='Arsenal')
    probable = dataset.build_probable_lineup(
        league_code='epl',
        team_name='Arsenal',
        unavailable_players={'Bukayo Saka'},
        recent_games=1,
    )

    assert market_value is not None
    assert market_value.total_market_value_eur == 362000000
    assert probable is not None
    assert probable.formation == '4-3-3'
    assert all(player.player_name != 'Bukayo Saka' for player in probable.players)


def test_soccerdata_client_reads_local_materialized_cache_without_live_backend(tmp_path) -> None:
    db_path = tmp_path / 'analytics.duckdb'
    con = duckdb.connect(str(db_path))
    con.execute(
        '''
        CREATE TABLE sd_team_season_cache (
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
    con.execute(
        '''
        CREATE TABLE sd_team_match_cache (
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
    con.execute(
        '''
        CREATE TABLE sd_team_shot_cache (
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
    con.executemany(
        'INSERT INTO sd_team_season_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            ('epl', 2025, 'Arsenal', 32.0, 58.0, 420.0, 160.0, 54.2, 49.8),
            ('epl', 2025, 'Tottenham Hotspur', 32.0, 56.0, 390.0, 150.0, 51.7, 47.3),
        ],
    )
    con.executemany(
        'INSERT INTO sd_team_match_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            ('epl', 2025, 'Arsenal', 1001, '2026-04-10 12:00:00', 3, 2.1, 2.0, 1.0, 1.9, 0.8),
            ('epl', 2025, 'Arsenal', 1002, '2026-04-03 12:00:00', 1, 1.6, 1.0, 1.0, 1.5, 0.9),
            (
                'epl',
                2025,
                'Tottenham Hotspur',
                1003,
                '2026-04-10 12:00:00',
                0,
                0.7,
                1.0,
                2.0,
                0.9,
                1.7,
            ),
            (
                'epl',
                2025,
                'Tottenham Hotspur',
                1004,
                '2026-04-03 12:00:00',
                3,
                2.2,
                3.0,
                1.0,
                2.1,
                0.8,
            ),
        ],
    )
    con.executemany(
        'INSERT INTO sd_team_shot_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [
            ('epl', 2025, 'Arsenal', 1001, 7, 2, 1.45, 5),
            ('epl', 2025, 'Arsenal', 1002, 5, 1, 1.05, 4),
            ('epl', 2025, 'Tottenham Hotspur', 1003, 4, 1, 0.82, 3),
            ('epl', 2025, 'Tottenham Hotspur', 1004, 8, 3, 1.76, 6),
        ],
    )
    con.close()

    client = SoccerDataClient(
        team_catalog=load_team_catalog(),
        backend=ExplodingSoccerDataBackend(),
        database_path=db_path,
    )

    bundle = client.fetch_fixture_enrichment(
        fixture=sample_fixtures('epl', season=2025)[0],
        recent_matches=2,
    )

    assert bundle.home.season_metrics is not None
    assert bundle.home.season_metrics.xg == 54.2
    assert bundle.home.recent_form is not None
    assert bundle.home.recent_form.points == 4
    assert bundle.home.shot_summary is not None
    assert bundle.home.shot_summary.shots == 12
