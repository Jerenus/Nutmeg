from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActionCommand, ActionStatus, ActorRole
from nutmeg.ontology.repository.actions import ActionRepository
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
