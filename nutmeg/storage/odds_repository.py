from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.config.settings import AppSettings
from nutmeg.domain.odds import HistoricalMarketPoint, OddsProviderEvent, OddsSnapshot
from nutmeg.storage.duckdb_utils import connect_analytics_db


def _to_storage_datetime(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _from_storage_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


class DuckDbOddsHistoryRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._db_path = settings.analytics_db_path

    def append_snapshot(self, snapshot: OddsSnapshot) -> None:
        captured_at = snapshot.provider.updated_at or datetime.now(UTC)
        rows: list[tuple[object, ...]] = []
        for market in snapshot.markets.values():
            for outcome in market.outcomes:
                rows.append(
                    (
                        snapshot.fixture.fixture_id,
                        snapshot.provider.name,
                        _to_storage_datetime(captured_at),
                        market.market_key,
                        market.line,
                        snapshot.provider.bookmaker_count,
                        outcome.outcome_key,
                        outcome.fair_probability,
                        outcome.fair_odds,
                        outcome.best_odds,
                    )
                )
        if not rows:
            return
        with connect_analytics_db(self._db_path) as connection:
            connection.executemany(
                '''
                INSERT INTO odds_market_history (
                    fixture_id,
                    provider,
                    captured_at,
                    market_key,
                    line,
                    bookmaker_count,
                    outcome_key,
                    fair_probability,
                    fair_odds,
                    best_odds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                rows,
            )

    def list_market_history(
        self,
        fixture_id: str,
        *,
        market_key: str,
        line: str | None,
        limit: int = 20,
    ) -> list[HistoricalMarketPoint]:
        predicate = 'line IS NULL' if line is None else 'line = ?'
        params: list[object] = [fixture_id, market_key]
        if line is not None:
            params.append(line)
        with connect_analytics_db(self._db_path) as connection:
            rows = connection.execute(
                f'''
                SELECT
                    captured_at,
                    provider,
                    bookmaker_count,
                    outcome_key,
                    fair_probability,
                    fair_odds,
                    best_odds
                FROM odds_market_history
                WHERE fixture_id = ?
                  AND market_key = ?
                  AND {predicate}
                ORDER BY captured_at ASC, outcome_key ASC
                ''',
                params,
            ).fetchall()

        grouped: dict[tuple[datetime, str], dict[str, object]] = {}
        for (
            captured_at,
            provider,
            bookmaker_count,
            outcome_key,
            fair_probability,
            fair_odds,
            best_odds,
        ) in rows:
            key = (captured_at, provider)
            entry = grouped.setdefault(
                key,
                {
                    'captured_at': captured_at,
                    'provider': provider,
                    'bookmaker_count': bookmaker_count,
                    'outcome_probabilities': {},
                    'outcome_fair_odds': {},
                    'outcome_best_odds': {},
                },
            )
            if fair_probability is not None:
                entry['outcome_probabilities'][outcome_key] = float(fair_probability)
            if fair_odds is not None:
                entry['outcome_fair_odds'][outcome_key] = float(fair_odds)
            if best_odds is not None:
                entry['outcome_best_odds'][outcome_key] = float(best_odds)

        points = [
            HistoricalMarketPoint(
                captured_at=_from_storage_datetime(entry['captured_at']),
                provider=str(entry['provider']),
                market_key=market_key,
                line=line,
                outcome_probabilities=entry['outcome_probabilities'],
                outcome_fair_odds=entry['outcome_fair_odds'],
                outcome_best_odds=entry['outcome_best_odds'],
                bookmaker_count=int(entry['bookmaker_count']),
            )
            for entry in grouped.values()
        ]
        if limit > 0:
            return points[-limit:]
        return points


class DuckDbOddsEventRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._db_path = settings.analytics_db_path

    def get_event(self, fixture_id: str, *, provider: str) -> OddsProviderEvent | None:
        with connect_analytics_db(self._db_path) as connection:
            row = connection.execute(
                '''
                SELECT
                    fixture_id,
                    provider,
                    sport_key,
                    event_id,
                    home_team,
                    away_team,
                    commence_time,
                    matched_at
                FROM odds_provider_events
                WHERE fixture_id = ?
                  AND provider = ?
                ''',
                [fixture_id, provider],
            ).fetchone()
        if row is None:
            return None
        return OddsProviderEvent(
            fixture_id=str(row[0]),
            provider=str(row[1]),
            sport_key=str(row[2]),
            event_id=str(row[3]),
            home_team=str(row[4]),
            away_team=str(row[5]),
            commence_time=_from_storage_datetime(row[6]),
            matched_at=_from_storage_datetime(row[7]),
        )

    def upsert_event(self, event: OddsProviderEvent) -> None:
        with connect_analytics_db(self._db_path) as connection:
            connection.execute(
                '''
                DELETE FROM odds_provider_events
                WHERE fixture_id = ?
                  AND provider = ?
                ''',
                [event.fixture_id, event.provider],
            )
            connection.execute(
                '''
                INSERT INTO odds_provider_events (
                    fixture_id,
                    provider,
                    sport_key,
                    event_id,
                    home_team,
                    away_team,
                    commence_time,
                    matched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    event.fixture_id,
                    event.provider,
                    event.sport_key,
                    event.event_id,
                    event.home_team,
                    event.away_team,
                    _to_storage_datetime(event.commence_time),
                    _to_storage_datetime(event.matched_at),
                ],
            )


    def delete_event(self, fixture_id: str, *, provider: str) -> None:
        with connect_analytics_db(self._db_path) as connection:
            connection.execute(
                '''
                DELETE FROM odds_provider_events
                WHERE fixture_id = ?
                  AND provider = ?
                ''',
                [fixture_id, provider],
            )


class DuckDbOddsProviderHealthRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._db_path = settings.analytics_db_path

    def get_latest(self, provider: str):
        from nutmeg.data.the_odds_api import TheOddsApiHealthSnapshot

        with connect_analytics_db(self._db_path) as connection:
            row = connection.execute(
                '''
                SELECT
                    provider,
                    cache_hits,
                    cache_misses,
                    reconcile_attempts,
                    reconcile_failures,
                    stale_refresh_attempts,
                    stale_refresh_successes,
                    last_event_id,
                    last_error,
                    updated_at
                FROM odds_provider_health
                WHERE provider = ?
                ''',
                [provider],
            ).fetchone()
        if row is None:
            return None
        return TheOddsApiHealthSnapshot(
            provider=str(row[0]),
            cache_hits=int(row[1]),
            cache_misses=int(row[2]),
            reconcile_attempts=int(row[3]),
            reconcile_failures=int(row[4]),
            stale_refresh_attempts=int(row[5]),
            stale_refresh_successes=int(row[6]),
            last_event_id=str(row[7]) if row[7] is not None else None,
            last_error=str(row[8]) if row[8] is not None else None,
            updated_at=_from_storage_datetime(row[9]),
        )

    def record_snapshot(self, snapshot) -> None:
        updated_at = snapshot.updated_at or datetime.now(UTC)
        with connect_analytics_db(self._db_path) as connection:
            connection.execute(
                'DELETE FROM odds_provider_health WHERE provider = ?',
                [snapshot.provider],
            )
            connection.execute(
                '''
                INSERT INTO odds_provider_health (
                    provider,
                    cache_hits,
                    cache_misses,
                    reconcile_attempts,
                    reconcile_failures,
                    stale_refresh_attempts,
                    stale_refresh_successes,
                    last_event_id,
                    last_error,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    snapshot.provider,
                    snapshot.cache_hits,
                    snapshot.cache_misses,
                    snapshot.reconcile_attempts,
                    snapshot.reconcile_failures,
                    snapshot.stale_refresh_attempts,
                    snapshot.stale_refresh_successes,
                    snapshot.last_event_id,
                    snapshot.last_error,
                    _to_storage_datetime(updated_at),
                ],
            )
