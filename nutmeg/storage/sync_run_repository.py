from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from nutmeg.domain.sync import SyncRunSummary
from nutmeg.storage.state_models import SyncRunRecord


class SqlAlchemySyncRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_run(self, provider: str, resource: str, scope: str) -> int:
        record = SyncRunRecord(
            provider=provider,
            resource=resource,
            scope=scope,
            status='running',
            started_at=datetime.now(UTC),
            finished_at=None,
            fixtures_written=0,
            requests_made=0,
            details=None,
        )
        self._session.add(record)
        self._session.flush()
        return int(record.id)

    def mark_success(self, run_id: int, summary: SyncRunSummary) -> None:
        record = self._session.get(SyncRunRecord, run_id)
        if record is None:
            raise KeyError(f'Unknown sync run id {run_id}')
        record.status = summary.status
        record.finished_at = summary.finished_at
        record.fixtures_written = summary.fixtures_written
        record.requests_made = summary.requests_made
        record.details = summary.details
        self._session.flush()

    def mark_failure(self, run_id: int, message: str) -> None:
        record = self._session.get(SyncRunRecord, run_id)
        if record is None:
            raise KeyError(f'Unknown sync run id {run_id}')
        record.status = 'failed'
        record.finished_at = datetime.now(UTC)
        record.details = message
        self._session.flush()

    def latest(self) -> SyncRunSummary | None:
        stmt = select(SyncRunRecord).order_by(SyncRunRecord.started_at.desc()).limit(1)
        record = self._session.scalars(stmt).first()
        if record is None:
            return None
        return SyncRunSummary(
            provider=record.provider,
            resource=record.resource,
            scope=record.scope,
            status=record.status,
            started_at=record.started_at,
            finished_at=record.finished_at or record.started_at,
            fixtures_written=record.fixtures_written,
            requests_made=record.requests_made,
            details=record.details,
        )
