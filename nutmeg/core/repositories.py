from __future__ import annotations

from typing import Protocol

from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.odds import HistoricalMarketPoint, OddsProviderEvent, OddsSnapshot
from nutmeg.domain.sync import SyncRunSummary


class FixtureRepository(Protocol):
    def list_upcoming(self, league: str, days: int) -> list[Fixture]:
        ...

    def get_fixture(self, fixture_id: str) -> Fixture | None:
        ...

    def get_latest_finished_for_team_before(
        self,
        *,
        league: str,
        team_id: int | None,
        team_name: str,
        before,
    ) -> Fixture | None:
        ...

    def upsert_many(self, fixtures: list[Fixture]) -> int:
        ...


class SyncRunRepository(Protocol):
    def create_run(self, provider: str, resource: str, scope: str) -> int:
        ...

    def mark_success(self, run_id: int, summary: SyncRunSummary) -> None:
        ...

    def mark_failure(self, run_id: int, message: str) -> None:
        ...

    def latest(self) -> SyncRunSummary | None:
        ...


class OddsHistoryRepository(Protocol):
    def append_snapshot(self, snapshot: OddsSnapshot) -> None:
        ...

    def list_market_history(
        self,
        fixture_id: str,
        *,
        market_key: str,
        line: str | None,
        limit: int = 20,
    ) -> list[HistoricalMarketPoint]:
        ...


class OddsEventRepository(Protocol):
    def get_event(self, fixture_id: str, *, provider: str) -> OddsProviderEvent | None:
        ...

    def upsert_event(self, event: OddsProviderEvent) -> None:
        ...

    def delete_event(self, fixture_id: str, *, provider: str) -> None:
        ...
