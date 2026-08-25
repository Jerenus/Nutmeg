from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActionCommand, ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (value TEXT NOT NULL)"))
    return ActionService(lambda: OntologyUnitOfWork(engine)), engine


def _command(key: str = "outbox:one", *, role: ActorRole = ActorRole.CONNECTOR):
    return ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="source:test",
        actor_role=role,
        idempotency_key=key,
        payload={"key": key},
        requested_at=datetime(2026, 8, 24, 10, tzinfo=UTC),
    )


def test_committed_action_and_event_share_transaction(tmp_path: Path) -> None:
    service, engine = _setup(tmp_path)

    outcome = service.execute(
        _command(), lambda _uow, _command: (ObjectRef("probe", "1"),)
    )

    with OntologyUnitOfWork(engine) as uow:
        events = uow.outbox.after(0, limit=10)
    assert [(event.action_id, event.topic) for event in events] == [
        (outcome.action_id, "action.committed")
    ]
    assert events[0].object_type == "probe"
    assert events[0].object_id == "1"
    assert events[0].payload == {
        "action_type": "ingest_artifact",
        "result_refs": [{"object_id": "1", "object_type": "probe"}],
        "status": "committed",
    }


def test_handler_failure_has_only_failed_terminal_event(tmp_path: Path) -> None:
    service, engine = _setup(tmp_path)

    def fail_after_business_write(uow, _command):
        uow.connection.execute(text("INSERT INTO probe(value) VALUES ('partial')"))
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        service.execute(_command("outbox:failure"), fail_after_business_write)

    with OntologyUnitOfWork(engine) as uow:
        events = uow.outbox.after(0, limit=10)
        business_count = uow.connection.execute(
            text("SELECT COUNT(*) FROM probe")
        ).scalar_one()
    assert business_count == 0
    assert [event.topic for event in events] == ["action.failed"]


def test_permission_rejection_publishes_rejected_event(tmp_path: Path) -> None:
    service, engine = _setup(tmp_path)

    outcome = service.execute(
        _command("outbox:denied", role=ActorRole.AI_ANALYST),
        lambda _uow, _command: pytest.fail("handler called"),
    )

    assert outcome.status is ActionStatus.REJECTED
    with OntologyUnitOfWork(engine) as uow:
        events = uow.outbox.after(0, limit=10)
    assert [event.topic for event in events] == ["action.rejected"]


def test_outbox_cursor_resumes_without_duplication(tmp_path: Path) -> None:
    service, engine = _setup(tmp_path)
    service.execute(_command("outbox:one"), lambda _uow, _command: ())
    service.execute(_command("outbox:two"), lambda _uow, _command: ())

    with OntologyUnitOfWork(engine) as uow:
        first = uow.outbox.after(0, limit=1)
        second = uow.outbox.after(first[0].sequence, limit=10)

    assert len(first) == 1
    assert len(second) == 1
    assert second[0].sequence > first[0].sequence
    assert first[0].event_id != second[0].event_id
    with OntologyUnitOfWork(engine) as uow:
        assert uow.outbox.count() == 2
        assert uow.outbox.latest_sequence() == second[0].sequence


def test_kernel_status_exposes_durable_outbox_cursor(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=b"event-backed",
            content_type="text/plain",
            source_name="test",
            source_type="fixture",
            actor_id="source:test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="outbox:kernel:1",
            retrieved_at=datetime(2026, 8, 24, 10, tzinfo=UTC),
        )
    )

    status = kernel.status()

    assert status.outbox_event_count == 1
    assert status.outbox_latest_sequence == 1
    assert status.to_dict()["outbox_latest_sequence"] == 1
