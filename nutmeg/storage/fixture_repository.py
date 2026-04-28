from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nutmeg.config.settings import AppSettings
from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.storage.duckdb_utils import connect_analytics_db


def _to_storage_datetime(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _from_storage_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


class DuckDbFixtureRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._db_path = settings.analytics_db_path

    def upsert_many(self, fixtures: list[Fixture]) -> int:
        if not fixtures:
            return 0
        now = datetime.now(UTC).replace(tzinfo=None)
        payload = [
            (
                fixture.fixture_id,
                fixture.league_code,
                fixture.provider_league_id,
                fixture.season,
                _to_storage_datetime(fixture.kickoff_at),
                fixture.home_team_id,
                fixture.away_team_id,
                fixture.home_team,
                fixture.away_team,
                fixture.source,
                fixture.status.value,
                fixture.status_short,
                fixture.status_long,
                fixture.round_name,
                fixture.venue,
                fixture.referee,
                fixture.home_goals,
                fixture.away_goals,
                now,
            )
            for fixture in fixtures
        ]
        with connect_analytics_db(self._db_path) as connection:
            connection.executemany(
                'DELETE FROM fixtures WHERE fixture_id = ?',
                [(fixture.fixture_id,) for fixture in fixtures],
            )
            connection.executemany(
                '''
                INSERT INTO fixtures (
                    fixture_id,
                    league_code,
                    provider_league_id,
                    season,
                    kickoff_at,
                    home_team_id,
                    away_team_id,
                    home_team,
                    away_team,
                    source,
                    status,
                    status_short,
                    status_long,
                    round_name,
                    venue,
                    referee,
                    home_goals,
                    away_goals,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                payload,
            )
        return len(fixtures)

    def list_upcoming(self, league: str, days: int) -> list[Fixture]:
        now = datetime.now(UTC).replace(tzinfo=None)
        cutoff = now + timedelta(days=days)
        with connect_analytics_db(self._db_path) as connection:
            rows = connection.execute(
                '''
                SELECT
                    fixture_id,
                    league_code,
                    provider_league_id,
                    season,
                    kickoff_at,
                    home_team_id,
                    away_team_id,
                    home_team,
                    away_team,
                    source,
                    status,
                    status_short,
                    status_long,
                    round_name,
                    venue,
                    referee,
                    home_goals,
                    away_goals
                FROM fixtures
                WHERE league_code = ?
                  AND kickoff_at >= ?
                  AND kickoff_at <= ?
                ORDER BY kickoff_at ASC
                ''',
                [league, now, cutoff],
            ).fetchall()
        return [self._row_to_fixture(row) for row in rows]

    def get_fixture(self, fixture_id: str) -> Fixture | None:
        with connect_analytics_db(self._db_path) as connection:
            row = connection.execute(
                '''
                SELECT
                    fixture_id,
                    league_code,
                    provider_league_id,
                    season,
                    kickoff_at,
                    home_team_id,
                    away_team_id,
                    home_team,
                    away_team,
                    source,
                    status,
                    status_short,
                    status_long,
                    round_name,
                    venue,
                    referee,
                    home_goals,
                    away_goals
                FROM fixtures
                WHERE fixture_id = ?
                ''',
                [fixture_id],
            ).fetchone()
        if row is None:
            return None
        return self._row_to_fixture(row)

    def get_latest_finished_for_team_before(
        self,
        *,
        league: str,
        team_id: int | None,
        team_name: str,
        before: datetime,
    ) -> Fixture | None:
        before_value = _to_storage_datetime(before)
        with connect_analytics_db(self._db_path) as connection:
            row = connection.execute(
                '''
                SELECT
                    fixture_id,
                    league_code,
                    provider_league_id,
                    season,
                    kickoff_at,
                    home_team_id,
                    away_team_id,
                    home_team,
                    away_team,
                    source,
                    status,
                    status_short,
                    status_long,
                    round_name,
                    venue,
                    referee,
                    home_goals,
                    away_goals
                FROM fixtures
                WHERE league_code = ?
                  AND status = ?
                  AND kickoff_at < ?
                  AND (
                    (? IS NOT NULL AND (home_team_id = ? OR away_team_id = ?))
                    OR home_team = ?
                    OR away_team = ?
                  )
                ORDER BY kickoff_at DESC
                LIMIT 1
                ''',
                [
                    league,
                    FixtureStatus.FINISHED.value,
                    before_value,
                    team_id,
                    team_id,
                    team_id,
                    team_name,
                    team_name,
                ],
            ).fetchone()
        if row is None:
            return None
        return self._row_to_fixture(row)

    def _row_to_fixture(self, row: tuple[object, ...]) -> Fixture:
        return Fixture(
            fixture_id=row[0],
            league_code=row[1],
            provider_league_id=row[2],
            season=row[3],
            kickoff_at=_from_storage_datetime(row[4]),
            home_team_id=row[5],
            away_team_id=row[6],
            home_team=row[7],
            away_team=row[8],
            source=row[9],
            status=FixtureStatus(row[10]),
            status_short=row[11],
            status_long=row[12],
            round_name=row[13],
            venue=row[14],
            referee=row[15],
            home_goals=row[16],
            away_goals=row[17],
        )
