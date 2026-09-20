from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActionCommand, ActionStatus, ActorRole
from nutmeg.ontology.repository.actions import ActionRepository
from nutmeg.ontology.repository.replay import HistoricalReplayRunRecord
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

AT = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    return kernel


def _command(
    action_type: str, key: str, payload: dict[str, object] | None = None,
) -> ActionCommand:
    return ActionCommand.create(
        action_type=action_type,
        actor_id="system:test",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key=key,
        payload=payload or {},
        requested_at=AT,
    )


def _commit(
    repository: ActionRepository,
    action_type: str,
    key: str,
    payload: dict[str, object] | None = None,
) -> None:
    command = _command(action_type, key, payload)
    repository.insert_accepted(command)
    repository.mark_committed(command.action_id, (), AT.isoformat())


def _reject(repository: ActionRepository, action_type: str, key: str) -> None:
    repository.insert_terminal(
        _command(action_type, key),
        ActionStatus.REJECTED,
        "permission_denied",
        None,
    )


def test_count_filters_action_truth_by_type_status_and_prefix(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    with OntologyUnitOfWork(kernel.engine) as uow:
        _commit(uow.actions, "build_market_snapshot", "zucai:snapshot:26111:1:x")
        _commit(uow.actions, "build_market_snapshot", "zucai:snapshot:26112:1:x")
        _reject(uow.actions, "build_market_snapshot", "zucai:snapshot:26111:2:x")
        _commit(uow.actions, "record_match", "zucai:match:26111:1")

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.actions.count() == 4
        assert uow.actions.count(action_type="build_market_snapshot") == 3
        assert uow.actions.count(status=ActionStatus.COMMITTED) == 3
        assert (
            uow.actions.count(
                action_type="build_market_snapshot",
                status=ActionStatus.COMMITTED,
                idempotency_prefix="zucai:snapshot:26111:",
            )
            == 1
        )


def test_count_snapshot_matches_uses_distinct_action_payload_truth(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    with OntologyUnitOfWork(kernel.engine) as uow:
        _commit(
            uow.actions,
            "build_market_snapshot",
            "zucai:snapshot:26110:1:x",
            {"match_id": "match-a", "provider": "zucai", "snapshot_kind": "read_time"},
        )
        _commit(
            uow.actions,
            "build_market_snapshot",
            "zucai:snapshot:26111:1:x",
            {"match_id": "match-a", "provider": "zucai", "snapshot_kind": "read_time"},
        )
        _commit(
            uow.actions,
            "build_market_snapshot",
            "zucai:snapshot:26111:2:x",
            {"match_id": "match-b", "provider": "zucai", "snapshot_kind": "read_time"},
        )
        _commit(
            uow.actions,
            "build_market_snapshot",
            "snap:intl:read_time:date:1:had",
            {"match_id": "match-b", "provider": "intl", "snapshot_kind": "read_time"},
        )

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.actions.count_committed_snapshot_matches(
            {"match-a", "match-b"}, provider="zucai", snapshot_kind="read_time"
        ) == 2


def test_action_repository_round_trips_replay_provenance(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.replay.insert_running(
            HistoricalReplayRunRecord(
                replay_run_id="replay-20260919-a",
                business_date="2026-09-19",
                source_root_fingerprint="source",
                source_manifest_hash="manifest",
                isolated_database_identity="/isolated/ontology.db",
                schema_version=35,
                status="running",
                started_at=AT.isoformat(),
                finished_at=None,
                production_before={},
                production_after=None,
                report_sha256=None,
                failure_codes=(),
            )
        )
        command = ActionCommand.create(
            action_type="ingest_artifact",
            actor_id="source:test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="artifact:replay",
            payload={},
            requested_at=AT,
            historical_replay=True,
            replay_run_id="replay-20260919-a",
        )
        uow.actions.insert_accepted(command)

    with OntologyUnitOfWork(kernel.engine) as uow:
        stored = uow.actions.get_by_idempotency_key("artifact:replay")
    assert stored is not None
    assert stored.historical_replay is True
    assert stored.replay_run_id == "replay-20260919-a"
