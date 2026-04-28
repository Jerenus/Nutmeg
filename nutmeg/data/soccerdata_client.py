from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Protocol

import duckdb
import pandas as pd

from nutmeg.config.catalog import get_league
from nutmeg.config.team_catalog import TeamCatalog, load_team_catalog
from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.snapshot import (
    SoccerDataFixtureBundle,
    TeamEnrichment,
    TeamRecentForm,
    TeamSeasonMetrics,
    TeamShotSummary,
)
from nutmeg.storage.duckdb_utils import connect_analytics_db


class SoccerDataError(RuntimeError):
    pass


def _load_soccerdata() -> Any:
    try:
        return importlib.import_module('soccerdata')
    except ImportError as exc:  # pragma: no cover
        raise SoccerDataError('soccerdata is not installed in the current environment.') from exc


class SoccerDataBackend(Protocol):
    def build_fbref_reader(self, **kwargs: object) -> Any:
        ...

    def build_understat_reader(self, **kwargs: object) -> Any:
        ...


class DefaultSoccerDataBackend:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir or Path('.nutmeg-data') / 'soccerdata'

    def build_fbref_reader(self, **kwargs: object) -> Any:
        sd = _load_soccerdata()
        return sd.FBref(data_dir=self._cache_dir / 'FBref', **kwargs)

    def build_understat_reader(self, **kwargs: object) -> Any:
        sd = _load_soccerdata()
        return sd.Understat(data_dir=self._cache_dir / 'Understat', **kwargs)


class SoccerDataClient:
    def __init__(
        self,
        *,
        team_catalog: TeamCatalog | None = None,
        backend: SoccerDataBackend | None = None,
        database_path: Path | None = None,
    ) -> None:
        self._team_catalog = team_catalog or load_team_catalog()
        self._backend = backend or DefaultSoccerDataBackend()
        self._database_path = database_path

    def fetch_fixture_enrichment(
        self,
        *,
        fixture: Fixture,
        recent_matches: int = 5,
    ) -> SoccerDataFixtureBundle:
        league = get_league(fixture.league_code)
        if not league.supports_soccerdata:
            raise SoccerDataError(
                f'League `{fixture.league_code}` does not have a supported soccerdata mapping yet.'
            )

        cached_bundle = self._fetch_cached_fixture_enrichment(
            fixture=fixture,
            recent_matches=recent_matches,
        )
        if cached_bundle is not None:
            return cached_bundle

        fbref_standard_rows = self._flatten_frame(
            self._backend.build_fbref_reader(
                leagues=league.soccerdata_league('fbref'),
                seasons=[fixture.season],
            ).read_team_season_stats(stat_type='standard')
        )
        fbref_shooting_rows = self._flatten_frame(
            self._backend.build_fbref_reader(
                leagues=league.soccerdata_league('fbref'),
                seasons=[fixture.season],
            ).read_team_season_stats(stat_type='shooting')
        )
        understat_reader = self._backend.build_understat_reader(
            leagues=league.soccerdata_league('understat'),
            seasons=[fixture.season],
        )
        understat_match_rows = self._flatten_frame(understat_reader.read_team_match_stats())

        home = self._build_team_enrichment(
            canonical_name=self._team_catalog.normalize(fixture.home_team),
            fbref_standard_rows=fbref_standard_rows,
            fbref_shooting_rows=fbref_shooting_rows,
            understat_match_rows=understat_match_rows,
            understat_reader=understat_reader,
            recent_matches=recent_matches,
        )
        away = self._build_team_enrichment(
            canonical_name=self._team_catalog.normalize(fixture.away_team),
            fbref_standard_rows=fbref_standard_rows,
            fbref_shooting_rows=fbref_shooting_rows,
            understat_match_rows=understat_match_rows,
            understat_reader=understat_reader,
            recent_matches=recent_matches,
        )
        return SoccerDataFixtureBundle(
            league_code=fixture.league_code,
            season=fixture.season,
            home=home,
            away=away,
        )

    def materialize_league_cache(self, league_code: str, season: int) -> int:
        if self._database_path is None:
            raise SoccerDataError('soccerdata materialization requires a database path.')

        league = get_league(league_code)
        if not league.supports_soccerdata:
            raise SoccerDataError(
                f'League `{league_code}` does not have a supported soccerdata mapping yet.'
            )

        fbref_standard_rows = self._flatten_frame(
            self._backend.build_fbref_reader(
                leagues=league.soccerdata_league('fbref'),
                seasons=[season],
            ).read_team_season_stats(stat_type='standard')
        )
        fbref_shooting_rows = self._flatten_frame(
            self._backend.build_fbref_reader(
                leagues=league.soccerdata_league('fbref'),
                seasons=[season],
            ).read_team_season_stats(stat_type='shooting')
        )
        understat_reader = self._backend.build_understat_reader(
            leagues=league.soccerdata_league('understat'),
            seasons=[season],
        )
        understat_match_rows = self._flatten_frame(understat_reader.read_team_match_stats())
        game_ids = [
            int(game_id)
            for game_id in understat_match_rows.get('game_id', pd.Series()).dropna().tolist()
        ]
        shot_rows = (
            self._flatten_frame(understat_reader.read_shot_events(match_id=game_ids))
            if game_ids
            else pd.DataFrame()
        )

        with connect_analytics_db(self._database_path) as connection:
            connection.execute(
                'DELETE FROM sd_team_season_cache WHERE league_code = ? AND season = ?',
                [league_code, season],
            )
            connection.execute(
                'DELETE FROM sd_team_match_cache WHERE league_code = ? AND season = ?',
                [league_code, season],
            )
            connection.execute(
                'DELETE FROM sd_team_shot_cache WHERE league_code = ? AND season = ?',
                [league_code, season],
            )
            for _, row in fbref_standard_rows.iterrows():
                team_name = str(row.get('team'))
                shooting_rows = fbref_shooting_rows[
                    fbref_shooting_rows['team'].astype(str) == team_name
                ]
                shooting_row = shooting_rows.iloc[0] if not shooting_rows.empty else pd.Series()
                season_metrics = self._extract_season_metrics(
                    standard_rows=pd.DataFrame([row]),
                    shooting_rows=pd.DataFrame([shooting_row]),
                    team_name=team_name,
                )
                if season_metrics is None:
                    continue
                canonical_team = self._team_catalog.normalize(team_name)
                connection.execute(
                    '''
                    INSERT INTO sd_team_season_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        league_code,
                        season,
                        canonical_team,
                        season_metrics.matches,
                        season_metrics.goals,
                        season_metrics.shots,
                        season_metrics.shots_on_target,
                        season_metrics.xg,
                        season_metrics.non_penalty_xg,
                    ],
                )
            for canonical_team in {
                self._team_catalog.normalize(team)
                for team in understat_match_rows.get('home_team', pd.Series()).astype(str).tolist()
                + understat_match_rows.get('away_team', pd.Series()).astype(str).tolist()
            }:
                provider_team = self._team_catalog.resolve_source_name(canonical_team, 'understat')
                recent_rows = self._select_recent_team_rows(
                    understat_match_rows,
                    team_name=provider_team,
                    limit=1000,
                )
                for _, row in recent_rows.iterrows():
                    connection.execute(
                        '''
                        INSERT INTO sd_team_match_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        [
                            league_code,
                            season,
                            canonical_team,
                            int(row['game_id']),
                            row['date'],
                            int(row['team_points']),
                            float(row['team_expected_points']),
                            float(row['team_goals_for']),
                            float(row['team_goals_against']),
                            float(row['team_xg_for']),
                            float(row['team_xg_against']),
                        ],
                    )
                team_shot_rows = shot_rows[shot_rows['team'].astype(str) == provider_team]
                if team_shot_rows.empty:
                    continue
                for game_id, game_rows in team_shot_rows.groupby('game_id'):
                    summary = self._extract_shot_summary(game_rows, team_name=provider_team)
                    if summary is None:
                        continue
                    connection.execute(
                        '''
                        INSERT INTO sd_team_shot_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        [
                            league_code,
                            season,
                            canonical_team,
                            int(game_id),
                            summary.shots,
                            summary.goals,
                            summary.total_xg,
                            summary.open_play_shots,
                        ],
                    )
            return int(
                connection.execute(
                    (
                        'SELECT COUNT(*) FROM sd_team_season_cache '
                        'WHERE league_code = ? AND season = ?'
                    ),
                    [league_code, season],
                ).fetchone()[0]
                or 0
            )

    def _build_team_enrichment(
        self,
        *,
        canonical_name: str,
        fbref_standard_rows: pd.DataFrame,
        fbref_shooting_rows: pd.DataFrame,
        understat_match_rows: pd.DataFrame,
        understat_reader: Any,
        recent_matches: int,
    ) -> TeamEnrichment:
        fbref_team = self._team_catalog.resolve_source_name(
            canonical_name,
            provider='fbref',
        )
        understat_team = self._team_catalog.resolve_source_name(
            canonical_name,
            provider='understat',
        )
        recent_rows = self._select_recent_team_rows(
            understat_match_rows,
            team_name=understat_team,
            limit=recent_matches,
        )
        recent_game_ids = [
            int(game_id)
            for game_id in recent_rows.get('game_id', pd.Series()).tolist()
        ]
        shot_rows = (
            self._flatten_frame(understat_reader.read_shot_events(match_id=recent_game_ids))
            if recent_game_ids
            else pd.DataFrame()
        )
        return TeamEnrichment(
            canonical_name=canonical_name,
            source_names={'fbref': fbref_team, 'understat': understat_team},
            season_metrics=self._extract_season_metrics(
                standard_rows=fbref_standard_rows,
                shooting_rows=fbref_shooting_rows,
                team_name=fbref_team,
            ),
            recent_form=self._extract_recent_form(recent_rows),
            shot_summary=self._extract_shot_summary(shot_rows, team_name=understat_team),
            market_value=None,
            injuries=[],
            lineup=None,
        )

    def _fetch_cached_fixture_enrichment(
        self,
        *,
        fixture: Fixture,
        recent_matches: int,
    ) -> SoccerDataFixtureBundle | None:
        if self._database_path is None:
            return None
        with connect_analytics_db(self._database_path) as connection:
            if not self._cache_tables_exist(connection):
                return None
            home = self._build_cached_team_enrichment(
                connection=connection,
                league_code=fixture.league_code,
                season=fixture.season,
                canonical_name=self._team_catalog.normalize(fixture.home_team),
                recent_matches=recent_matches,
            )
            away = self._build_cached_team_enrichment(
                connection=connection,
                league_code=fixture.league_code,
                season=fixture.season,
                canonical_name=self._team_catalog.normalize(fixture.away_team),
                recent_matches=recent_matches,
            )
        if home is None or away is None:
            return None
        return SoccerDataFixtureBundle(
            league_code=fixture.league_code,
            season=fixture.season,
            home=home,
            away=away,
        )

    def _build_cached_team_enrichment(
        self,
        *,
        connection: duckdb.DuckDBPyConnection,
        league_code: str,
        season: int,
        canonical_name: str,
        recent_matches: int,
    ) -> TeamEnrichment | None:
        season_row = connection.execute(
            '''
            SELECT matches, goals, shots, shots_on_target, xg, non_penalty_xg
            FROM sd_team_season_cache
            WHERE league_code = ? AND season = ? AND team_name = ?
            LIMIT 1
            ''',
            [league_code, season, canonical_name],
        ).fetchone()
        match_rows = connection.execute(
            '''
            SELECT game_id, points, expected_points, goals_for, goals_against, xg_for, xg_against
            FROM sd_team_match_cache
            WHERE league_code = ? AND season = ? AND team_name = ?
            ORDER BY date DESC
            LIMIT ?
            ''',
            [league_code, season, canonical_name, recent_matches],
        ).fetchall()
        shot_rows = connection.execute(
            '''
            SELECT game_id, shots, goals, total_xg, open_play_shots
            FROM sd_team_shot_cache
            WHERE league_code = ? AND season = ? AND team_name = ?
              AND game_id IN (
                SELECT game_id
                FROM sd_team_match_cache
                WHERE league_code = ? AND season = ? AND team_name = ?
                ORDER BY date DESC
                LIMIT ?
              )
            ''',
            [
                league_code,
                season,
                canonical_name,
                league_code,
                season,
                canonical_name,
                recent_matches,
            ],
        ).fetchall()
        if season_row is None:
            return None

        recent_form = None
        if match_rows:
            points = [int(row[1]) for row in match_rows]
            recent_form = TeamRecentForm(
                matches=len(match_rows),
                wins=sum(1 for value in points if value == 3),
                draws=sum(1 for value in points if value == 1),
                losses=sum(1 for value in points if value == 0),
                points=sum(points),
                expected_points=round(sum(float(row[2]) for row in match_rows), 2),
                goals_for=round(sum(float(row[3]) for row in match_rows), 2),
                goals_against=round(sum(float(row[4]) for row in match_rows), 2),
                xg_for=round(sum(float(row[5]) for row in match_rows), 2),
                xg_against=round(sum(float(row[6]) for row in match_rows), 2),
            )
        shot_summary = None
        if shot_rows:
            shot_summary = TeamShotSummary(
                shots=sum(int(row[1]) for row in shot_rows),
                goals=sum(int(row[2]) for row in shot_rows),
                total_xg=round(sum(float(row[3]) for row in shot_rows), 2),
                open_play_shots=sum(int(row[4]) for row in shot_rows),
            )
        return TeamEnrichment(
            canonical_name=canonical_name,
            source_names={
                'fbref': self._team_catalog.resolve_source_name(canonical_name, 'fbref'),
                'understat': self._team_catalog.resolve_source_name(canonical_name, 'understat'),
            },
            season_metrics=TeamSeasonMetrics(
                matches=float(season_row[0]) if season_row[0] is not None else None,
                goals=float(season_row[1]) if season_row[1] is not None else None,
                shots=float(season_row[2]) if season_row[2] is not None else None,
                shots_on_target=float(season_row[3]) if season_row[3] is not None else None,
                xg=float(season_row[4]) if season_row[4] is not None else None,
                non_penalty_xg=float(season_row[5]) if season_row[5] is not None else None,
            ),
            recent_form=recent_form,
            shot_summary=shot_summary,
            market_value=None,
            injuries=[],
            lineup=None,
        )

    def _cache_tables_exist(self, connection: duckdb.DuckDBPyConnection) -> bool:
        for table_name in ('sd_team_season_cache', 'sd_team_match_cache', 'sd_team_shot_cache'):
            exists = connection.execute(
                '''
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_name = ?
                ''',
                [table_name],
            ).fetchone()[0]
            if not exists:
                return False
        return True

    def _extract_season_metrics(
        self,
        *,
        standard_rows: pd.DataFrame,
        shooting_rows: pd.DataFrame,
        team_name: str,
    ) -> TeamSeasonMetrics | None:
        standard_team_rows = standard_rows[standard_rows['team'].astype(str) == team_name]
        shooting_team_rows = shooting_rows[shooting_rows['team'].astype(str) == team_name]
        if standard_team_rows.empty and shooting_team_rows.empty:
            return None
        standard_row = standard_team_rows.iloc[0] if not standard_team_rows.empty else pd.Series()
        shooting_row = shooting_team_rows.iloc[0] if not shooting_team_rows.empty else pd.Series()
        return TeamSeasonMetrics(
            matches=self._float_value(standard_row, ['Playing Time__90s', '90s']),
            goals=self._float_value(
                standard_row,
                ['Standard__Gls', 'Performance__Gls', 'Gls'],
            ),
            shots=self._float_value(
                shooting_row,
                ['Standard__Sh', 'Performance__Sh', 'Sh'],
            ),
            shots_on_target=self._float_value(
                shooting_row,
                ['Standard__SoT', 'Performance__SoT', 'SoT'],
            ),
            xg=self._float_value(standard_row, ['Expected__xG', 'xG']),
            non_penalty_xg=self._float_value(standard_row, ['Expected__npxG', 'npxG']),
        )

    def _extract_recent_form(self, frame: pd.DataFrame) -> TeamRecentForm | None:
        if frame.empty:
            return None
        points = frame['team_points'].fillna(0).astype(float)
        return TeamRecentForm(
            matches=len(frame.index),
            wins=int((points == 3).sum()),
            draws=int((points == 1).sum()),
            losses=int((points == 0).sum()),
            points=int(points.sum()),
            expected_points=float(
                round(frame['team_expected_points'].fillna(0).astype(float).sum(), 2)
            ),
            goals_for=float(round(frame['team_goals_for'].fillna(0).astype(float).sum(), 2)),
            goals_against=float(
                round(frame['team_goals_against'].fillna(0).astype(float).sum(), 2)
            ),
            xg_for=float(round(frame['team_xg_for'].fillna(0).astype(float).sum(), 2)),
            xg_against=float(round(frame['team_xg_against'].fillna(0).astype(float).sum(), 2)),
        )

    def _extract_shot_summary(
        self,
        frame: pd.DataFrame,
        *,
        team_name: str,
    ) -> TeamShotSummary | None:
        if frame.empty:
            return None
        team_rows = frame[frame['team'].astype(str) == team_name]
        if team_rows.empty:
            return None
        results = team_rows['result'].astype(str).str.replace(' ', '').str.lower()
        situations = team_rows['situation'].astype(str).str.replace(' ', '').str.lower()
        return TeamShotSummary(
            shots=len(team_rows.index),
            goals=int((results == 'goal').sum()),
            total_xg=float(round(team_rows['xg'].fillna(0).astype(float).sum(), 2)),
            open_play_shots=int((situations == 'openplay').sum()),
        )

    def _select_recent_team_rows(
        self,
        frame: pd.DataFrame,
        *,
        team_name: str,
        limit: int,
    ) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()

        home_rows = frame[frame['home_team'].astype(str) == team_name].copy()
        away_rows = frame[frame['away_team'].astype(str) == team_name].copy()
        if not home_rows.empty:
            home_rows['team_points'] = home_rows['home_points']
            home_rows['team_expected_points'] = home_rows['home_expected_points']
            home_rows['team_goals_for'] = home_rows['home_goals']
            home_rows['team_goals_against'] = home_rows['away_goals']
            home_rows['team_xg_for'] = home_rows['home_xg']
            home_rows['team_xg_against'] = home_rows['away_xg']
        if not away_rows.empty:
            away_rows['team_points'] = away_rows['away_points']
            away_rows['team_expected_points'] = away_rows['away_expected_points']
            away_rows['team_goals_for'] = away_rows['away_goals']
            away_rows['team_goals_against'] = away_rows['home_goals']
            away_rows['team_xg_for'] = away_rows['away_xg']
            away_rows['team_xg_against'] = away_rows['home_xg']
        combined = pd.concat([home_rows, away_rows], ignore_index=True)
        if combined.empty:
            return combined
        return combined.sort_values('date', ascending=False).head(limit)

    def _flatten_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()
        flattened = frame.reset_index()
        flattened.columns = [self._flatten_column(column) for column in flattened.columns]
        return flattened

    def _flatten_column(self, column: object) -> str:
        if not isinstance(column, tuple):
            return str(column)
        return '__'.join(str(part) for part in column if part not in {'', None})

    def _float_value(self, row: pd.Series, candidates: list[str]) -> float | None:
        for candidate in candidates:
            if candidate in row and pd.notna(row[candidate]):
                return float(row[candidate])
        return None


__all__ = ['SoccerDataClient', 'SoccerDataError', 'SoccerDataFixtureBundle']
