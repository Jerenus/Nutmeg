from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterator

import duckdb

from nutmeg.config.catalog import get_league
from nutmeg.config.team_catalog import TeamCatalog, load_team_catalog
from nutmeg.domain.snapshot import (
    BenchDepthContext,
    LineupPlayer,
    TeamLineup,
    TeamMarketValue,
)
from nutmeg.storage.duckdb_utils import connect_analytics_db

REMOTE_TABLE_URLS = {
    'clubs': 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/clubs.csv.gz',
    'players': 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/players.csv.gz',
    'games': 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/games.csv.gz',
    'game_lineups': 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/game_lineups.csv.gz',
}

POSITION_GROUPS = {
    'goalkeeper': 'Goalkeeper',
    'keeper': 'Goalkeeper',
    'defender': 'Defender',
    'centre-back': 'Defender',
    'center-back': 'Defender',
    'left-back': 'Defender',
    'right-back': 'Defender',
    'full-back': 'Defender',
    'wing-back': 'Defender',
    'midfielder': 'Midfielder',
    'defensive midfield': 'Midfielder',
    'defensive midfielder': 'Midfielder',
    'attacking midfield': 'Midfielder',
    'attacking midfielder': 'Midfielder',
    'central midfield': 'Midfielder',
    'central midfielder': 'Midfielder',
    'attack': 'Attack',
    'forward': 'Attack',
    'striker': 'Attack',
    'centre-forward': 'Attack',
    'center-forward': 'Attack',
    'left winger': 'Attack',
    'right winger': 'Attack',
    'winger': 'Attack',
    'second striker': 'Attack',
}


class TransfermarktDataset:
    def __init__(
        self,
        *,
        database_path: Path | None = None,
        team_catalog: TeamCatalog | None = None,
    ) -> None:
        self._database_path = database_path
        self._team_catalog = team_catalog or load_team_catalog()

    def fetch_team_market_value(
        self,
        league_code: str,
        team_name: str,
    ) -> TeamMarketValue | None:
        club_id = self._resolve_club_id(league_code=league_code, team_name=team_name)
        if club_id is None:
            return None

        with self._connect() as connection:
            total_market_value = connection.execute(
                f'''
                SELECT COALESCE(SUM(COALESCE(market_value_in_eur, 0)), 0)
                FROM {self._table(connection, 'players')}
                WHERE current_club_id = ?
                ''',
                [club_id],
            ).fetchone()[0]
            top_players = connection.execute(
                f'''
                SELECT name, COALESCE(market_value_in_eur, 0) AS market_value_in_eur
                FROM {self._table(connection, 'players')}
                WHERE current_club_id = ?
                ORDER BY market_value_in_eur DESC, name ASC
                LIMIT 3
                ''',
                [club_id],
            ).fetchall()

        return TeamMarketValue(
            source='transfermarkt-datasets',
            total_market_value_eur=int(total_market_value or 0),
            top_players=[(name, int(value or 0)) for name, value in top_players],
        )

    def build_probable_lineup(
        self,
        *,
        league_code: str,
        team_name: str,
        unavailable_players: set[str],
        recent_games: int = 5,
    ) -> TeamLineup | None:
        club_id = self._resolve_club_id(league_code=league_code, team_name=team_name)
        if club_id is None:
            return None

        with self._connect() as connection:
            recent_games_cte = f'''
                WITH recent_games AS (
                    SELECT
                        game_id,
                        date,
                        CASE
                            WHEN home_club_id = {club_id} THEN home_club_formation
                            ELSE away_club_formation
                        END AS formation
                    FROM {self._table(connection, 'games')}
                    WHERE home_club_id = {club_id} OR away_club_id = {club_id}
                    ORDER BY date DESC
                    LIMIT {int(recent_games)}
                )
            '''
            formation_row = connection.execute(
                recent_games_cte
                + '''
                SELECT formation, COUNT(*) AS appearances
                FROM recent_games
                WHERE formation IS NOT NULL AND formation <> ''
                GROUP BY formation
                ORDER BY appearances DESC, formation ASC
                LIMIT 1
                '''
            ).fetchone()
            lineup_rows = []
            if self._database_path is not None and self._table_exists(
                connection,
                'tm_game_lineups_cache',
            ):
                lineup_rows = connection.execute(
                    recent_games_cte
                    + f'''
                    SELECT
                        gl.player_name,
                        gl.position,
                        gl.number,
                        MAX(COALESCE(p.market_value_in_eur, 0)) AS market_value,
                        COUNT(*) AS starts,
                        MAX(gl.date) AS last_started,
                        MAX(COALESCE(gl.team_captain, 0)) AS is_captain
                    FROM {self._table(connection, 'game_lineups')} gl
                    JOIN recent_games rg ON rg.game_id = gl.game_id
                    LEFT JOIN {self._table(connection, 'players')} p ON p.player_id = gl.player_id
                    WHERE gl.club_id = ?
                      AND gl.type = 'starting_lineup'
                    GROUP BY gl.player_name, gl.position, gl.number
                    ORDER BY starts DESC, last_started DESC, market_value DESC, gl.player_name ASC
                    LIMIT 20
                    ''',
                    [club_id],
                ).fetchall()

            players = [
                LineupPlayer(
                    player_name=row[0],
                    position=row[1],
                    shirt_number=row[2],
                    role='starter',
                    captain=bool(row[6]),
                )
                for row in lineup_rows
                if row[0] not in unavailable_players
            ][:11]
            if not players:
                squad_rows = connection.execute(
                    f'''
                    SELECT name, position, COALESCE(market_value_in_eur, 0) AS market_value_in_eur
                    FROM {self._table(connection, 'players')}
                    WHERE current_club_id = ?
                    ORDER BY market_value_in_eur DESC, name ASC
                    LIMIT 40
                    ''',
                    [club_id],
                ).fetchall()
                players = self._build_squad_probable_players(
                    squad_rows=squad_rows,
                    formation=formation_row[0] if formation_row else None,
                    unavailable_players=unavailable_players,
                )
            if not players:
                return None

        return TeamLineup(
            status='probable',
            source='transfermarkt-datasets',
            formation=formation_row[0] if formation_row else None,
            players=players,
        )

    def build_bench_depth_context(
        self,
        *,
        league_code: str,
        team_name: str,
        unavailable_players: set[str],
        starting_players: set[str],
    ) -> BenchDepthContext | None:
        club_id = self._resolve_club_id(league_code=league_code, team_name=team_name)
        if club_id is None:
            return None

        with self._connect() as connection:
            squad_rows = connection.execute(
                f'''
                SELECT name, COALESCE(market_value_in_eur, 0) AS market_value_in_eur
                FROM {self._table(connection, 'players')}
                WHERE current_club_id = ?
                ORDER BY market_value_in_eur DESC, name ASC
                LIMIT 60
                ''',
                [club_id],
            ).fetchall()
        available_rows = [
            row
            for row in squad_rows
            if row[0] not in unavailable_players and row[0] not in starting_players
        ]
        available_players = len(available_rows)
        bench_market_value = sum(int(row[1] or 0) for row in available_rows[:7])
        return BenchDepthContext(
            bench_market_value_eur=bench_market_value,
            available_players=available_players,
            label=self._bench_depth_label(bench_market_value, available_players),
            source='transfermarkt-datasets',
        )

    def _build_squad_probable_players(
        self,
        *,
        squad_rows: list[tuple[str, str | None, int]],
        formation: str | None,
        unavailable_players: set[str],
    ) -> list[LineupPlayer]:
        available_rows = [
            row for row in squad_rows if row[0] not in unavailable_players
        ]
        if not available_rows:
            return []

        quotas = self._formation_quotas(formation)
        grouped_rows: dict[str, list[tuple[str, str | None, int]]] = {
            'Goalkeeper': [],
            'Defender': [],
            'Midfielder': [],
            'Attack': [],
        }
        fallback_rows: list[tuple[str, str | None, int]] = []
        for row in available_rows:
            position_group = self._position_group(row[1])
            if position_group is None:
                fallback_rows.append(row)
                continue
            grouped_rows[position_group].append(row)

        selected_names: set[str] = set()
        selected_players: list[LineupPlayer] = []
        selected_counts = {group_name: 0 for group_name, _ in quotas}
        for group_name, count in quotas:
            for row in grouped_rows[group_name]:
                if selected_counts[group_name] >= count:
                    break
                if row[0] in selected_names:
                    continue
                selected_players.append(
                    LineupPlayer(
                        player_name=row[0],
                        position=row[1],
                        shirt_number=None,
                        role='starter',
                        captain=False,
                    )
                )
                selected_names.add(row[0])
                selected_counts[group_name] += 1

        remaining_rows = [row for row in available_rows if row[0] not in selected_names]
        for row in remaining_rows:
            if len(selected_players) >= 11:
                break
            selected_players.append(
                LineupPlayer(
                    player_name=row[0],
                    position=row[1],
                    shirt_number=None,
                    role='starter',
                    captain=False,
                )
            )
            selected_names.add(row[0])
        return selected_players[:11]

    def _formation_quotas(self, formation: str | None) -> list[tuple[str, int]]:
        if not formation:
            return [('Goalkeeper', 1), ('Defender', 4), ('Midfielder', 3), ('Attack', 3)]
        parts = [part for part in formation.split('-') if part.isdigit()]
        if len(parts) < 3:
            return [('Goalkeeper', 1), ('Defender', 4), ('Midfielder', 3), ('Attack', 3)]
        defenders = int(parts[0])
        attackers = int(parts[-1])
        midfielders = sum(int(part) for part in parts[1:-1])
        return [
            ('Goalkeeper', 1),
            ('Defender', defenders),
            ('Midfielder', midfielders),
            ('Attack', attackers),
        ]

    def _position_group(self, position: str | None) -> str | None:
        if position is None:
            return None
        normalized = position.strip().lower()
        if normalized in POSITION_GROUPS:
            return POSITION_GROUPS[normalized]
        for key, group in POSITION_GROUPS.items():
            if key in normalized:
                return group
        return None

    def _bench_depth_label(self, bench_market_value: int, available_players: int) -> str:
        if bench_market_value >= 200_000_000 or available_players >= 12:
            return 'strong'
        if bench_market_value >= 100_000_000 or available_players >= 8:
            return 'balanced'
        return 'thin'

    def _resolve_club_id(self, *, league_code: str, team_name: str) -> int | None:
        league = get_league(league_code)
        team_source_name = self._team_catalog.resolve_source_name(team_name, 'transfermarkt')

        with self._connect() as connection:
            row = connection.execute(
                f'''
                SELECT club_id
                FROM {self._table(connection, 'clubs')}
                WHERE name = ?
                  AND (? IS NULL OR domestic_competition_id = ?)
                LIMIT 1
                ''',
                [
                    team_source_name,
                    league.transfermarkt_competition_id,
                    league.transfermarkt_competition_id,
                ],
            ).fetchone()
        if row is None:
            return None
        return int(row[0])

    @contextlib.contextmanager
    def _connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        if self._database_path:
            with connect_analytics_db(self._database_path) as connection:
                yield connection
            return
        with duckdb.connect() as connection:
            connection.execute('INSTALL httpfs; LOAD httpfs;')
            yield connection

    def materialize_local_cache(self, league_codes: list[str] | None = None) -> int:
        if self._database_path is None:
            raise RuntimeError(
                'Transfermarkt local cache materialization requires a database path.'
            )

        target_codes = league_codes or ['epl', 'laliga', 'serie-a', 'bundesliga', 'ligue-1']
        competition_ids = [
            get_league(code).transfermarkt_competition_id
            for code in target_codes
            if get_league(code).transfermarkt_competition_id is not None
        ]
        quoted_ids = ', '.join(f"'{competition_id}'" for competition_id in competition_ids)

        with self._connect() as connection:
            connection.execute('INSTALL httpfs; LOAD httpfs;')
            connection.execute('DELETE FROM tm_clubs_cache')
            connection.execute(
                f'''
                INSERT INTO tm_clubs_cache
                SELECT club_id, name, domestic_competition_id
                FROM {self._remote_table('clubs')}
                WHERE domestic_competition_id IN ({quoted_ids})
                '''
            )
            connection.execute('DELETE FROM tm_players_cache')
            connection.execute(
                f'''
                INSERT INTO tm_players_cache
                SELECT p.player_id, p.name, p.current_club_id, p.position, p.market_value_in_eur
                FROM {self._remote_table('players')} p
                JOIN tm_clubs_cache c ON c.club_id = p.current_club_id
                '''
            )
            connection.execute('DELETE FROM tm_games_cache')
            connection.execute(
                f'''
                INSERT INTO tm_games_cache
                SELECT
                    g.game_id,
                    g.date,
                    g.home_club_id,
                    g.away_club_id,
                    g.home_club_formation,
                    g.away_club_formation
                FROM {self._remote_table('games')} g
                WHERE g.home_club_id IN (SELECT club_id FROM tm_clubs_cache)
                   OR g.away_club_id IN (SELECT club_id FROM tm_clubs_cache)
                '''
            )
            return int(
                connection.execute(
                    'SELECT COUNT(*) FROM tm_players_cache'
                ).fetchone()[0]
                or 0
            )

    def _table(self, connection: duckdb.DuckDBPyConnection, name: str) -> str:
        if self._database_path is None:
            return self._remote_table(name)
        cache_name = f'tm_{name}_cache'
        if self._table_exists(connection, cache_name):
            return cache_name
        if self._table_exists(connection, name):
            return name
        return self._remote_table(name)

    def _table_exists(self, connection: duckdb.DuckDBPyConnection, table_name: str) -> bool:
        return bool(
            connection.execute(
                '''
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_name = ?
                ''',
                [table_name],
            ).fetchone()[0]
        )

    def _remote_table(self, name: str) -> str:
        return f"read_csv_auto('{REMOTE_TABLE_URLS[name]}')"
