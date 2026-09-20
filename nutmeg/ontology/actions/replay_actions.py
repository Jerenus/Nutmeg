"""Typed Actions governing historical replay run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService, ReplayActionContext
from nutmeg.ontology.repository.replay import HistoricalReplayRunRecord


@dataclass(frozen=True, slots=True)
class StartHistoricalReplayRequest:
    replay_run_id: str
    business_date: str
    source_root_fingerprint: str
    source_manifest_hash: str
    isolated_database_identity: str
    production_database_identity: str
    schema_version: int
    production_before: dict[str, object]
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class FinishHistoricalReplayRequest:
    replay_run_id: str
    business_date: str
    isolated_database_identity: str
    status: str
    production_after: dict[str, object]
    report_sha256: str
    failure_codes: tuple[str, ...]
    idempotency_key: str
    requested_at: datetime


class ReplayActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def start(self, request: StartHistoricalReplayRequest) -> ActionOutcome:
        isolated = Path(request.isolated_database_identity).resolve()
        production = Path(request.production_database_identity).resolve()
        if isolated == production:
            raise ValueError("isolated ontology path equals production ontology path")
        with self._action_service.unit_of_work() as uow:
            existing = uow.replay.get(request.replay_run_id)
        if existing is not None and (
            existing.business_date != request.business_date
            or existing.source_root_fingerprint != request.source_root_fingerprint
            or existing.source_manifest_hash != request.source_manifest_hash
            or existing.isolated_database_identity != str(isolated)
        ):
            raise ValueError("historical replay run identity conflict")
        command = ActionCommand.create(
            action_type="start_historical_replay",
            actor_id="system:historical-replay",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=request.idempotency_key,
            payload={
                "replay_run_id": request.replay_run_id,
                "business_date": request.business_date,
                "source_root_fingerprint": request.source_root_fingerprint,
                "source_manifest_hash": request.source_manifest_hash,
                "isolated_database_identity": str(isolated),
                "production_database_identity": str(production),
                "schema_version": request.schema_version,
                "production_before": request.production_before,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action):
            uow.replay.insert_running(
                HistoricalReplayRunRecord(
                    replay_run_id=request.replay_run_id,
                    business_date=request.business_date,
                    source_root_fingerprint=request.source_root_fingerprint,
                    source_manifest_hash=request.source_manifest_hash,
                    isolated_database_identity=str(isolated),
                    schema_version=request.schema_version,
                    status="running",
                    started_at=request.requested_at.astimezone(UTC).isoformat(),
                    finished_at=None,
                    production_before=request.production_before,
                    production_after=None,
                    report_sha256=None,
                    failure_codes=(),
                )
            )
            return (ObjectRef("historical_replay_run", request.replay_run_id),)

        return self._action_service.execute(command, handler)

    def finish(self, request: FinishHistoricalReplayRequest) -> ActionOutcome:
        context = ReplayActionContext(
            replay_run_id=request.replay_run_id,
            business_date=request.business_date,
            isolated_database_identity=str(
                Path(request.isolated_database_identity).resolve()
            ),
        )
        with self._action_service.unit_of_work() as uow:
            run = uow.replay.get(request.replay_run_id)
        if run is None or run.status != "running":
            raise ValueError("historical replay run is not active")
        service = self._action_service.bind_replay(context)
        command = ActionCommand.create(
            action_type="finish_historical_replay",
            actor_id="system:historical-replay",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=request.idempotency_key,
            payload={
                "business_date": request.business_date,
                "status": request.status,
                "production_after": request.production_after,
                "report_sha256": request.report_sha256,
                "failure_codes": list(request.failure_codes),
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action):
            uow.replay.finish(
                request.replay_run_id,
                status=request.status,
                finished_at=request.requested_at.astimezone(UTC).isoformat(),
                production_after=request.production_after,
                report_sha256=request.report_sha256,
                failure_codes=request.failure_codes,
            )
            return (ObjectRef("historical_replay_run", request.replay_run_id),)

        return service.execute(command, handler)


__all__ = [
    "FinishHistoricalReplayRequest",
    "ReplayActions",
    "StartHistoricalReplayRequest",
]
