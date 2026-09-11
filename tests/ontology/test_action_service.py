from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from nutmeg.ontology.actions.models import ActionCommand, ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import IdempotencyConflictError, PermissionDeniedError
from nutmeg.ontology.repository.actions import ActionRepository
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _service(tmp_path: Path) -> tuple[ActionService, object]:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (value TEXT NOT NULL)"))
    return ActionService(lambda: OntologyUnitOfWork(engine)), engine


def _command(
    payload: dict[str, object] | None = None,
    *,
    key: str = "probe:one",
    role: ActorRole = ActorRole.CONNECTOR,
) -> ActionCommand:
    return ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="source:test",
        actor_role=role,
        idempotency_key=key,
        payload=payload or {"value": "one"},
        requested_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
    )


def _counts(engine) -> tuple[int, int, int]:
    with OntologyUnitOfWork(engine) as uow:
        return (
            uow.actions.count(),
            uow.connection.execute(text("SELECT COUNT(*) FROM probe")).scalar_one(),
            uow.outbox.count(),
        )


def test_action_commits_once_and_replays_stored_outcome(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    calls = 0

    def handler(uow, command):
        nonlocal calls
        calls += 1
        uow.connection.execute(text("INSERT INTO probe(value) VALUES (:value)"), command.payload)
        return (ObjectRef("probe", str(command.payload["value"])),)

    first = service.execute(_command(), handler)
    second = service.execute(_command(), handler)
    assert first.status is ActionStatus.COMMITTED
    assert second.action_id == first.action_id
    assert calls == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM probe")).scalar_one() == 1


def test_same_key_with_different_request_is_rejected(tmp_path: Path) -> None:
    service, _engine = _service(tmp_path)
    service.execute(_command(), lambda _uow, _command: ())
    with pytest.raises(IdempotencyConflictError, match="probe:one"):
        service.execute(_command({"value": "different"}), lambda _uow, _command: ())


def test_handler_failure_rolls_back_business_rows_but_persists_failed_action(
    tmp_path: Path,
) -> None:
    service, engine = _service(tmp_path)

    def failing(uow, command):
        uow.connection.execute(text("INSERT INTO probe(value) VALUES ('partial')"))
        raise RuntimeError("handler exploded")

    with pytest.raises(RuntimeError, match="handler exploded"):
        service.execute(_command(), failing)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM probe")).scalar_one() == 0
        record = ActionRepository(connection).get_by_idempotency_key("probe:one")
        assert record is not None
        assert record.status is ActionStatus.FAILED


def test_permission_denial_is_audited_without_calling_handler(tmp_path: Path) -> None:
    service, _engine = _service(tmp_path)
    command = ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="model:test",
        actor_role=ActorRole.AI_ANALYST,
        idempotency_key="probe:denied",
        payload={},
        requested_at=datetime.now(UTC),
    )
    outcome = service.execute(command, lambda _uow, _command: pytest.fail("handler called"))
    assert outcome.status is ActionStatus.REJECTED
    assert outcome.error_code == "permission_denied"


def test_batch_commits_actions_business_rows_and_outbox_atomically(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)

    def handler(uow, command):
        uow.connection.execute(text("INSERT INTO probe(value) VALUES (:value)"), command.payload)
        return (ObjectRef("probe", str(command.payload["value"])),)

    outcomes = service.execute_batch(
        (
            (_command(key="probe:batch:one"), handler),
            (_command({"value": "two"}, key="probe:batch:two"), handler),
        )
    )

    assert [outcome.status for outcome in outcomes] == [
        ActionStatus.COMMITTED,
        ActionStatus.COMMITTED,
    ]
    assert [outcome.result_refs[0].object_id for outcome in outcomes] == ["one", "two"]
    assert _counts(engine) == (2, 2, 2)


def test_batch_duplicate_key_is_rejected_before_handlers_and_writes(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    calls = 0

    def handler(_uow, _command):
        nonlocal calls
        calls += 1
        return ()

    with pytest.raises(IdempotencyConflictError, match="duplicate.*probe:duplicate"):
        service.execute_batch(
            (
                (_command(key="probe:duplicate"), handler),
                (_command(key="probe:duplicate"), handler),
            )
        )

    assert calls == 0
    assert _counts(engine) == (0, 0, 0)


def test_batch_existing_hash_conflict_is_rejected_before_handlers_and_writes(
    tmp_path: Path,
) -> None:
    service, engine = _service(tmp_path)
    service.execute(_command(key="probe:existing"), lambda _uow, _command: ())
    calls = 0

    def handler(_uow, _command):
        nonlocal calls
        calls += 1
        return ()

    with pytest.raises(IdempotencyConflictError, match="probe:existing"):
        service.execute_batch(
            (
                (_command(key="probe:new"), handler),
                (
                    _command({"value": "different"}, key="probe:existing"),
                    handler,
                ),
            )
        )

    assert calls == 0
    assert _counts(engine) == (1, 0, 1)


def test_batch_permission_denial_is_rejected_before_handlers_and_writes(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)
    calls = 0

    def handler(_uow, _command):
        nonlocal calls
        calls += 1
        return ()

    with pytest.raises(PermissionDeniedError, match="ai_analyst"):
        service.execute_batch(
            (
                (_command(key="probe:allowed"), handler),
                (
                    _command(key="probe:denied", role=ActorRole.AI_ANALYST),
                    handler,
                ),
            )
        )

    assert calls == 0
    assert _counts(engine) == (0, 0, 0)


def test_batch_replays_committed_action_and_only_executes_new_handler(tmp_path: Path) -> None:
    service, engine = _service(tmp_path)

    def insert_probe(uow, command):
        uow.connection.execute(text("INSERT INTO probe(value) VALUES (:value)"), command.payload)
        return (ObjectRef("probe", str(command.payload["value"])),)

    existing = service.execute(_command(key="probe:replay"), insert_probe)
    calls = 0

    def new_handler(uow, command):
        nonlocal calls
        calls += 1
        return insert_probe(uow, command)

    outcomes = service.execute_batch(
        (
            (
                _command(key="probe:replay"),
                lambda _uow, _command: pytest.fail("replay handler called"),
            ),
            (_command({"value": "new"}, key="probe:new"), new_handler),
        )
    )

    assert outcomes[0].action_id == existing.action_id
    assert outcomes[1].status is ActionStatus.COMMITTED
    assert calls == 1
    assert _counts(engine) == (2, 2, 2)


def test_batch_handler_failure_rolls_back_all_actions_business_rows_and_outbox(
    tmp_path: Path,
) -> None:
    service, engine = _service(tmp_path)

    def insert_probe(uow, command):
        uow.connection.execute(text("INSERT INTO probe(value) VALUES (:value)"), command.payload)
        return ()

    def fail_after_insert(uow, command):
        insert_probe(uow, command)
        raise RuntimeError("batch handler exploded")

    with pytest.raises(RuntimeError, match="batch handler exploded"):
        service.execute_batch(
            (
                (_command(key="probe:batch:first"), insert_probe),
                (
                    _command({"value": "second"}, key="probe:batch:second"),
                    fail_after_insert,
                ),
            )
        )

    assert _counts(engine) == (0, 0, 0)


def test_failed_attempt_does_not_block_a_corrected_retry(tmp_path: Path) -> None:
    """失败的尝试不得阻挡对它的修正。

    出生事故 2026-09-11：scoreboard 镜像因缺 `--supersedes` 失败，随后每一次**带上**
    supersedes 的重试都被判为 "idempotency key was reused with a different request"——
    因为请求哈希检查排在 FAILED 检查之前。结果是唯一能通过的办法变成"改 detail 扰动哈希"，
    也就是**为了绕过幂等而污染业务内容**。FAILED 行是审计记录，不是对这把键的占有。
    """
    service, engine = _service(tmp_path)

    def failing(_uow, _command):
        raise RuntimeError("missing supersedes")

    with pytest.raises(RuntimeError, match="missing supersedes"):
        service.execute(_command({"value": "one"}), failing)

    corrected = service.execute(
        _command({"value": "one", "supersedes": "sbo-1"}),
        lambda _uow, _command: (ObjectRef("probe", "fixed"),),
    )
    assert corrected.status is ActionStatus.COMMITTED
    with engine.connect() as connection:
        record = ActionRepository(connection).get_by_idempotency_key("probe:one")
        assert record is not None and record.status is ActionStatus.COMMITTED


def test_committed_outcome_still_blocks_a_different_request(tmp_path: Path) -> None:
    """已提交的结果仍然占据这把键——放宽只针对 FAILED，不动幂等本身。"""
    service, _engine = _service(tmp_path)
    service.execute(_command(), lambda _uow, _command: ())
    with pytest.raises(IdempotencyConflictError, match="probe:one"):
        service.execute(_command({"value": "changed"}), lambda _uow, _command: ())
