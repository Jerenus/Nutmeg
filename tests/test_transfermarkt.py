from __future__ import annotations

import duckdb

from nutmeg.config.team_catalog import load_team_catalog
from nutmeg.data.transfermarkt import TransfermarktDataset
from nutmeg.domain.snapshot import BenchDepthContext, TeamLineup, TeamMarketValue


def test_transfermarkt_dataset_builds_market_value_and_probable_lineup(tmp_path) -> None:
    db_path = tmp_path / 'transfermarkt.duckdb'
    con = duckdb.connect(str(db_path))
    con.execute(
        '''
        CREATE TABLE clubs (
            club_id BIGINT,
            name VARCHAR,
            domestic_competition_id VARCHAR
        )
        '''
    )
    con.execute(
        '''
        CREATE TABLE players (
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
        CREATE TABLE games (
            game_id BIGINT,
            date DATE,
            home_club_id BIGINT,
            away_club_id BIGINT,
            home_club_formation VARCHAR,
            away_club_formation VARCHAR
        )
        '''
    )
    con.execute(
        '''
        CREATE TABLE game_lineups (
            game_lineups_id VARCHAR,
            date DATE,
            game_id BIGINT,
            player_id BIGINT,
            club_id BIGINT,
            player_name VARCHAR,
            type VARCHAR,
            position VARCHAR,
            number VARCHAR,
            team_captain BIGINT
        )
        '''
    )
    con.executemany(
        'INSERT INTO clubs VALUES (?, ?, ?)',
        [
            (11, 'Arsenal Football Club', 'GB1'),
        ],
    )
    con.executemany(
        'INSERT INTO players VALUES (?, ?, ?, ?, ?)',
        [
            (1, 'David Raya', 11, 'Goalkeeper', 32000000),
            (2, 'Ben White', 11, 'Defender', 50000000),
            (3, 'William Saliba', 11, 'Defender', 80000000),
            (4, 'Gabriel Magalhaes', 11, 'Defender', 70000000),
            (5, 'Oleksandr Zinchenko', 11, 'Defender', 35000000),
            (6, 'Martin Odegaard', 11, 'Midfielder', 90000000),
            (7, 'Declan Rice', 11, 'Midfielder', 110000000),
            (8, 'Kai Havertz', 11, 'Attack', 70000000),
            (9, 'Bukayo Saka', 11, 'Attack', 140000000),
            (10, 'Gabriel Martinelli', 11, 'Attack', 65000000),
            (11, 'Leandro Trossard', 11, 'Attack', 30000000),
            (12, 'Injured Player', 11, 'Attack', 25000000),
        ],
    )
    con.executemany(
        'INSERT INTO games VALUES (?, ?, ?, ?, ?, ?)',
        [
            (1001, '2026-04-01', 11, 31, '4-3-3', '4-3-3'),
            (1002, '2026-04-08', 42, 11, '4-2-3-1', '4-3-3'),
            (1003, '2026-04-15', 11, 148, '4-3-3', '4-2-3-1'),
        ],
    )
    con.executemany(
        'INSERT INTO game_lineups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            (
                'a1',
                '2026-04-01',
                1001,
                1,
                11,
                'David Raya',
                'starting_lineup',
                'Goalkeeper',
                '22',
                0,
            ),
            (
                'a2',
                '2026-04-01',
                1001,
                2,
                11,
                'Ben White',
                'starting_lineup',
                'Defender',
                '4',
                0,
            ),
            (
                'a3',
                '2026-04-01',
                1001,
                3,
                11,
                'William Saliba',
                'starting_lineup',
                'Defender',
                '2',
                0,
            ),
            (
                'a4',
                '2026-04-01',
                1001,
                4,
                11,
                'Gabriel Magalhaes',
                'starting_lineup',
                'Defender',
                '6',
                0,
            ),
            (
                'a5',
                '2026-04-01',
                1001,
                5,
                11,
                'Oleksandr Zinchenko',
                'starting_lineup',
                'Defender',
                '17',
                0,
            ),
            (
                'a6',
                '2026-04-01',
                1001,
                6,
                11,
                'Martin Odegaard',
                'starting_lineup',
                'Midfielder',
                '8',
                1,
            ),
            (
                'a7',
                '2026-04-01',
                1001,
                7,
                11,
                'Declan Rice',
                'starting_lineup',
                'Midfielder',
                '41',
                0,
            ),
            (
                'a8',
                '2026-04-01',
                1001,
                8,
                11,
                'Kai Havertz',
                'starting_lineup',
                'Attack',
                '29',
                0,
            ),
            (
                'a9',
                '2026-04-01',
                1001,
                9,
                11,
                'Bukayo Saka',
                'starting_lineup',
                'Attack',
                '7',
                0,
            ),
            (
                'a10',
                '2026-04-01',
                1001,
                10,
                11,
                'Gabriel Martinelli',
                'starting_lineup',
                'Attack',
                '11',
                0,
            ),
            (
                'a11',
                '2026-04-01',
                1001,
                11,
                11,
                'Leandro Trossard',
                'starting_lineup',
                'Attack',
                '19',
                0,
            ),
            (
                'a12',
                '2026-04-08',
                1002,
                12,
                11,
                'Injured Player',
                'starting_lineup',
                'Attack',
                '14',
                0,
            ),
        ],
    )
    con.close()

    dataset = TransfermarktDataset(
        database_path=db_path,
        team_catalog=load_team_catalog(),
    )

    market_value = dataset.fetch_team_market_value(league_code='epl', team_name='Arsenal')
    lineup = dataset.build_probable_lineup(
        league_code='epl',
        team_name='Arsenal',
        unavailable_players={'Injured Player'},
        recent_games=3,
    )

    assert market_value == TeamMarketValue(
        source='transfermarkt-datasets',
        total_market_value_eur=797000000,
        top_players=[
            ('Bukayo Saka', 140000000),
            ('Declan Rice', 110000000),
            ('Martin Odegaard', 90000000),
        ],
    )
    assert lineup == TeamLineup(
        status='probable',
        source='transfermarkt-datasets',
        formation='4-3-3',
        players=lineup.players,
    )
    assert len(lineup.players) == 11
    assert all(player.player_name != 'Injured Player' for player in lineup.players)


def test_transfermarkt_dataset_builds_probable_lineup_without_lineup_history(
    tmp_path,
) -> None:
    db_path = tmp_path / 'transfermarkt.duckdb'
    con = duckdb.connect(str(db_path))
    con.execute(
        '''
        CREATE TABLE clubs (
            club_id BIGINT,
            name VARCHAR,
            domestic_competition_id VARCHAR
        )
        '''
    )
    con.execute(
        '''
        CREATE TABLE players (
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
        CREATE TABLE games (
            game_id BIGINT,
            date DATE,
            home_club_id BIGINT,
            away_club_id BIGINT,
            home_club_formation VARCHAR,
            away_club_formation VARCHAR
        )
        '''
    )
    con.execute(
        '''
        CREATE TABLE game_lineups (
            game_lineups_id VARCHAR,
            date DATE,
            game_id BIGINT,
            player_id BIGINT,
            club_id BIGINT,
            player_name VARCHAR,
            type VARCHAR,
            position VARCHAR,
            number VARCHAR,
            team_captain BIGINT
        )
        '''
    )
    con.executemany(
        'INSERT INTO clubs VALUES (?, ?, ?)',
        [
            (11, 'Arsenal Football Club', 'GB1'),
        ],
    )
    con.executemany(
        'INSERT INTO players VALUES (?, ?, ?, ?, ?)',
        [
            (1, 'David Raya', 11, 'Goalkeeper', 32000000),
            (2, 'Ben White', 11, 'Defender', 50000000),
            (3, 'William Saliba', 11, 'Defender', 80000000),
            (4, 'Gabriel Magalhaes', 11, 'Defender', 70000000),
            (5, 'Jurrien Timber', 11, 'Defender', 55000000),
            (6, 'Riccardo Calafiori', 11, 'Defender', 45000000),
            (7, 'Martin Odegaard', 11, 'Midfielder', 90000000),
            (8, 'Declan Rice', 11, 'Midfielder', 110000000),
            (9, 'Mikel Merino', 11, 'Midfielder', 42000000),
            (10, 'Bukayo Saka', 11, 'Attack', 140000000),
            (11, 'Kai Havertz', 11, 'Attack', 70000000),
            (12, 'Gabriel Martinelli', 11, 'Attack', 65000000),
            (13, 'Leandro Trossard', 11, 'Attack', 30000000),
        ],
    )
    con.executemany(
        'INSERT INTO games VALUES (?, ?, ?, ?, ?, ?)',
        [
            (1001, '2026-04-01', 11, 31, '4-3-3', '4-3-3'),
            (1002, '2026-04-08', 42, 11, '4-2-3-1', '4-3-3'),
            (1003, '2026-04-15', 11, 148, '4-3-3', '4-2-3-1'),
        ],
    )
    con.close()

    dataset = TransfermarktDataset(
        database_path=db_path,
        team_catalog=load_team_catalog(),
    )

    lineup = dataset.build_probable_lineup(
        league_code='epl',
        team_name='Arsenal',
        unavailable_players={'Ben White'},
        recent_games=3,
    )

    assert lineup == TeamLineup(
        status='probable',
        source='transfermarkt-datasets',
        formation='4-3-3',
        players=lineup.players,
    )
    assert lineup is not None
    assert len(lineup.players) == 11
    player_names = [player.player_name for player in lineup.players]
    assert 'David Raya' in player_names
    assert 'Ben White' not in player_names


def test_transfermarkt_dataset_builds_bench_depth_context(tmp_path) -> None:
    db_path = tmp_path / 'transfermarkt.duckdb'
    con = duckdb.connect(str(db_path))
    con.execute(
        '''
        CREATE TABLE clubs (
            club_id BIGINT,
            name VARCHAR,
            domestic_competition_id VARCHAR
        )
        '''
    )
    con.execute(
        '''
        CREATE TABLE players (
            player_id BIGINT,
            name VARCHAR,
            current_club_id BIGINT,
            position VARCHAR,
            market_value_in_eur BIGINT
        )
        '''
    )
    con.executemany(
        'INSERT INTO clubs VALUES (?, ?, ?)',
        [(11, 'Arsenal Football Club', 'GB1')],
    )
    con.executemany(
        'INSERT INTO players VALUES (?, ?, ?, ?, ?)',
        [
            (1, 'David Raya', 11, 'Goalkeeper', 32000000),
            (2, 'Ben White', 11, 'Defender', 50000000),
            (3, 'William Saliba', 11, 'Defender', 80000000),
            (4, 'Gabriel Magalhaes', 11, 'Defender', 70000000),
            (5, 'Jurrien Timber', 11, 'Defender', 55000000),
            (6, 'Riccardo Calafiori', 11, 'Defender', 45000000),
            (7, 'Martin Odegaard', 11, 'Midfielder', 90000000),
            (8, 'Declan Rice', 11, 'Midfielder', 110000000),
            (9, 'Mikel Merino', 11, 'Midfielder', 42000000),
            (10, 'Bukayo Saka', 11, 'Attack', 140000000),
            (11, 'Kai Havertz', 11, 'Attack', 70000000),
            (12, 'Gabriel Martinelli', 11, 'Attack', 65000000),
            (13, 'Leandro Trossard', 11, 'Attack', 30000000),
        ],
    )
    con.close()

    dataset = TransfermarktDataset(
        database_path=db_path,
        team_catalog=load_team_catalog(),
    )

    bench_depth = dataset.build_bench_depth_context(
        league_code='epl',
        team_name='Arsenal',
        unavailable_players={'Bukayo Saka'},
        starting_players={'David Raya', 'William Saliba', 'Declan Rice', 'Martin Odegaard'},
    )

    assert bench_depth == BenchDepthContext(
        bench_market_value_eur=397000000,
        available_players=8,
        label='strong',
        source='transfermarkt-datasets',
    )
