from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nutmeg.config.catalog import select_leagues
from nutmeg.core.repositories import FixtureRepository, SyncRunRepository
from nutmeg.data.api_football import ApiFootballClient
from nutmeg.domain.sync import LeagueSyncSummary, SyncRunSummary


@dataclass(slots=True, frozen=True)
class FixtureSyncReport:
    leagues: list[LeagueSyncSummary]
    total_fixtures: int
    total_requests: int
    started_at: datetime
    finished_at: datetime


class FixtureSyncService:
    def __init__(
        self,
        fixture_repository: FixtureRepository,
        sync_run_repository: SyncRunRepository,
        api_client: ApiFootballClient,
    ) -> None:
        self._fixture_repository = fixture_repository
        self._sync_run_repository = sync_run_repository
        self._api_client = api_client

    def sync(
        self,
        league_codes: list[str] | None,
        days: int,
        timezone: str,
        now: datetime | None = None,
        past_days: int = 0,
    ) -> FixtureSyncReport:
        now = now or datetime.now(UTC)
        start_date = now.date() - timedelta(days=max(past_days, 0))
        end_date = now.date() + timedelta(days=days)
        leagues = select_leagues(league_codes)
        scope = ','.join(league.code for league in leagues)
        run_id = self._sync_run_repository.create_run(
            provider='api-football',
            resource='fixtures',
            scope=scope,
        )
        summaries: list[LeagueSyncSummary] = []
        try:
            for league in leagues:
                season = league.resolve_season(now)
                batch = self._api_client.fetch_upcoming_fixtures(
                    league_code=league.code,
                    league_id=league.api_football_id,
                    season=season,
                    date_from=start_date,
                    date_to=end_date,
                    timezone=timezone,
                )
                fixtures_written = self._fixture_repository.upsert_many(batch.fixtures)
                summaries.append(
                    LeagueSyncSummary(
                        league_code=league.code,
                        fixtures_written=fixtures_written,
                        requests_made=batch.requests_made,
                        season=season,
                        synced_at=datetime.now(UTC),
                        quota_requests_remaining=batch.quota.requests_remaining,
                        quota_minute_remaining=batch.quota.minute_remaining,
                    )
                )
            finished_at = datetime.now(UTC)
            report = FixtureSyncReport(
                leagues=summaries,
                total_fixtures=sum(item.fixtures_written for item in summaries),
                total_requests=sum(item.requests_made for item in summaries),
                started_at=now,
                finished_at=finished_at,
            )
            self._sync_run_repository.mark_success(
                run_id,
                SyncRunSummary(
                    provider='api-football',
                    resource='fixtures',
                    scope=scope,
                    status='success',
                    started_at=now,
                    finished_at=finished_at,
                    fixtures_written=report.total_fixtures,
                    requests_made=report.total_requests,
                    details=(
                        f'synced {len(summaries)} competition(s) '
                        f'from {start_date.isoformat()} to {end_date.isoformat()}'
                    ),
                ),
            )
            return report
        except Exception as exc:
            self._sync_run_repository.mark_failure(run_id, str(exc))
            raise
        finally:
            close = getattr(self._api_client, 'close', None)
            if callable(close):
                close()
