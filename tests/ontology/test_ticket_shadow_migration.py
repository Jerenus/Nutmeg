from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, run_migrations
from nutmeg.ontology.repository.tickets import TicketShadowRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.test_m4_ticket_migration import (
    AuditedTicketArtifactRow,
    ConfirmationChallengeRow,
    _kernel,
    _revision,
)


def test_migration_16_upgrades_v15_once_and_grants_only_system(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine, migrations=MIGRATIONS[:15])

    first = run_migrations(engine, migrations=MIGRATIONS[:16])
    second = run_migrations(engine, migrations=MIGRATIONS[:16])

    assert first.applied_versions == (16,)
    assert second.applied_versions == ()
    assert "ticket_shadow_records" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        roles = connection.execute(
            select(schema.action_permissions.c.actor_role).where(
                schema.action_permissions.c.action_type == "mark_ticket_shadow"
            )
        ).scalars().all()
    assert roles == ["deterministic_system"]


def test_ticket_shadow_repository_round_trip(tmp_path: Path) -> None:
    kernel, _report, action_id, source_artifact_id = _kernel(tmp_path)
    revision = _revision(action_id, source_artifact_id)
    artifact = AuditedTicketArtifactRow(
        ticket_artifact_id="tat-1",
        ticket_batch_revision_id=revision.ticket_batch_revision_id,
        ticket_index=0,
        ticket_hash="ticket-hash",
        source_artifact_id=source_artifact_id,
        amount=100.0,
        currency="CNY",
        channel="jczq",
        deadline_at="2026-08-24T12:00:00+00:00",
        payload={"ticket": "T-1"},
        approved_at="2026-08-24T10:00:00+00:00",
        approved_by_action_id=action_id,
    )
    confirmation = ConfirmationChallengeRow(
        confirmation_id="tc-1",
        ticket_artifact_id="tat-1",
        nonce_hash="nonce-hash",
        ticket_hash="ticket-hash",
        amount=100.0,
        currency="CNY",
        channel="jczq",
        issued_at="2026-08-24T10:00:00+00:00",
        expires_at="2026-08-24T10:05:00+00:00",
        consumed_at=None,
        consumed_by_action_id=None,
    )
    shadow = TicketShadowRow(
        ticket_shadow_id="tsh-1",
        ticket_artifact_id="tat-1",
        confirmation_id="tc-1",
        reason="deadline_unconfirmed",
        deadline_at="2026-08-24T12:00:00+00:00",
        marked_at="2026-08-24T12:01:00+00:00",
        action_id=action_id,
    )

    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.tickets.insert_batch_revision(revision)
        uow.tickets.insert_ticket_artifact(artifact)
        uow.tickets.insert_confirmation(confirmation)
        uow.tickets.insert_shadow(shadow)

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.shadow_for_artifact("tat-1") == shadow
        assert uow.tickets.confirmation_by_nonce_hash("nonce-hash") == confirmation
