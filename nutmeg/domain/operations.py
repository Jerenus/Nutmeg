from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from nutmeg.domain.value import ValueCandidate


class TelegramDispatchStatus(StrEnum):
    SKIPPED = 'skipped'
    DRY_RUN = 'dry_run'
    SENT = 'sent'
    FAILED = 'failed'
    CONFIG_MISSING = 'config_missing'


@dataclass(slots=True, frozen=True)
class OperationPopularMatch:
    fixture_id: str
    rank: int
    home_team: str
    away_team: str
    score: int
    tier: str


@dataclass(slots=True, frozen=True)
class OperationBrief:
    fixture_id: str
    status: str
    verdict: str | None = None
    confidence: str | None = None
    error: str | None = None


@dataclass(slots=True, frozen=True)
class TelegramDispatch:
    status: TelegramDispatchStatus
    message: str | None = None
    chat_ids: list[int] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True, frozen=True)
class DailyRunSummary:
    league: str
    days: int
    generated_at: datetime
    dry_run: bool
    live_sync: bool
    sync_status: str
    sync_fixtures_written: int
    sync_requests_made: int
    fixtures_considered: int
    popular_matches: list[OperationPopularMatch]
    value_candidates: list[ValueCandidate]
    briefs: list[OperationBrief]
    telegram_dispatch: TelegramDispatch

