"""Durable historical replay run identity and terminal state."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, insert, select, update

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema


@dataclass(frozen=True, slots=True)
class HistoricalReplayRunRecord:
    replay_run_id: str
    business_date: str
    source_root_fingerprint: str
    source_manifest_hash: str
    isolated_database_identity: str
    schema_version: int
    status: str
    started_at: str
    finished_at: str | None
    production_before: dict[str, object]
    production_after: dict[str, object] | None
    report_sha256: str | None
    failure_codes: tuple[str, ...]


class HistoricalReplayRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_running(self, record: HistoricalReplayRunRecord) -> None:
        if (
            record.status != "running"
            or record.finished_at is not None
            or record.production_after is not None
            or record.report_sha256 is not None
            or record.failure_codes
        ):
            raise ValueError("new historical replay run must be running")
        self._connection.execute(
            insert(schema.historical_replay_runs).values(
                replay_run_id=record.replay_run_id,
                business_date=record.business_date,
                source_root_fingerprint=record.source_root_fingerprint,
                source_manifest_hash=record.source_manifest_hash,
                isolated_database_identity=record.isolated_database_identity,
                schema_version=record.schema_version,
                status=record.status,
                started_at=record.started_at,
                finished_at=None,
                production_before_json=canonical_json(record.production_before),
                production_after_json=None,
                report_sha256=None,
                failure_codes_json="[]",
            )
        )

    def get(self, replay_run_id: str) -> HistoricalReplayRunRecord | None:
        row = self._connection.execute(
            select(schema.historical_replay_runs).where(
                schema.historical_replay_runs.c.replay_run_id == replay_run_id
            )
        ).mappings().first()
        if row is None:
            return None
        return HistoricalReplayRunRecord(
            replay_run_id=row["replay_run_id"],
            business_date=row["business_date"],
            source_root_fingerprint=row["source_root_fingerprint"],
            source_manifest_hash=row["source_manifest_hash"],
            isolated_database_identity=row["isolated_database_identity"],
            schema_version=row["schema_version"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            production_before=json.loads(row["production_before_json"]),
            production_after=(
                None
                if row["production_after_json"] is None
                else json.loads(row["production_after_json"])
            ),
            report_sha256=row["report_sha256"],
            failure_codes=tuple(json.loads(row["failure_codes_json"])),
        )

    def finish(
        self,
        replay_run_id: str,
        *,
        status: str,
        finished_at: str,
        production_after: dict[str, object],
        report_sha256: str,
        failure_codes: tuple[str, ...],
    ) -> None:
        if status not in {"accepted", "failed"}:
            raise ValueError("historical replay terminal status is invalid")
        result = self._connection.execute(
            update(schema.historical_replay_runs)
            .where(
                schema.historical_replay_runs.c.replay_run_id == replay_run_id,
                schema.historical_replay_runs.c.status == "running",
            )
            .values(
                status=status,
                finished_at=finished_at,
                production_after_json=canonical_json(production_after),
                report_sha256=report_sha256,
                failure_codes_json=canonical_json(list(failure_codes)),
            )
        )
        if result.rowcount != 1:
            raise ValueError("historical replay run is not active")


__all__ = ["HistoricalReplayRepository", "HistoricalReplayRunRecord"]
