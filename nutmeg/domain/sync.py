from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True, frozen=True)
class LeagueSyncSummary:
    league_code: str
    fixtures_written: int
    requests_made: int
    season: int
    synced_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    quota_requests_remaining: int | None = None
    quota_minute_remaining: int | None = None


@dataclass(slots=True, frozen=True)
class SyncRunSummary:
    provider: str
    resource: str
    scope: str
    status: str
    started_at: datetime
    finished_at: datetime
    fixtures_written: int = 0
    requests_made: int = 0
    details: str | None = None
