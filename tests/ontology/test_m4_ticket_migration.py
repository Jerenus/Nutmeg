from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository import schema, schema_tickets
from nutmeg.ontology.repository.finance import CashAccountRow, TicketRow
from nutmeg.ontology.repository.tickets import (
    AuditedTicketArtifactRow,
    ConfirmationChallengeRow,
    TicketBatchRevisionRow,
    TicketPlacementRow,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

AT = "2026-08-24T10:00:00+00:00"
PROTECTED = {
    "create_ticket_batch",
    "remove_ticket_leg",
    "approve_ticket_batch",
    "issue_ticket_confirmation",
    "confirm_ticket_placement",
}


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    report = kernel.initialize()
    artifact = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=b'{"ticket":"artifact"}',
            content_type="application/vnd.nutmeg.ticket+json",
            source_name="m4-test",
            source_type="fixture",
            actor_id="source:m4-test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="m4:artifact",
            retrieved_at=datetime(2026, 8, 24, 10, tzinfo=UTC),
        )
    )
    artifact_id = next(
        ref.object_id
        for ref in artifact.result_refs
        if ref.object_type == "source_artifact"
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
    return kernel, report, artifact.action_id, artifact_id


def _revision(
    action_id: str,
    artifact_id: str,
    *,
    revision_no: int = 1,
    supersedes: str | None = None,
) -> TicketBatchRevisionRow:
    return TicketBatchRevisionRow(
        ticket_batch_revision_id=f"tbr-{revision_no}",
        ticket_batch_id="tb-1",
        revision_no=revision_no,
        supersedes_revision_id=supersedes,
        run_date="2026-08-24",
        channel="jczq",
        account_id="acct-jczq",
        currency="CNY",
        deadline_at="2026-08-24T12:00:00+00:00",
        input_legs=[{"leg_key": "match-1:home"}],
        composition={"n_tickets": 1},
        audit_findings=[],
        state="draft",
        content_hash=f"batch-hash-{revision_no}",
        source_artifact_id=artifact_id,
        created_at=AT,
        created_by_action_id=action_id,
    )


def test_migration_12_adds_protected_ticket_schema(tmp_path: Path) -> None:
    kernel, report, _action_id, _artifact_id = _kernel(tmp_path)

    assert report.applied_versions[-1] == 12
    assert {
        "ticket_batch_revisions",
        "audited_ticket_artifacts",
        "ticket_confirmation_challenges",
        "ticket_placements",
    } <= set(inspect(kernel.engine).get_table_names())
    with kernel.engine.connect() as connection:
        rows = connection.execute(select(schema.action_permissions)).mappings().all()
    seeded = {(row["action_type"], row["actor_role"]) for row in rows}
    assert {(action, "judge_operator") for action in PROTECTED} <= seeded
    assert not {(action, "ai_analyst") for action in PROTECTED} & seeded


def test_repository_round_trips_immutable_revisions_and_checks_current_version(
    tmp_path: Path,
) -> None:
    kernel, _report, action_id, artifact_id = _kernel(tmp_path)
    first = _revision(action_id, artifact_id)
    second = _revision(action_id, artifact_id, revision_no=2, supersedes="tbr-1")

    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.tickets.insert_batch_revision(first)
        assert uow.tickets.batch_revision("tbr-1") == first
        assert uow.tickets.current_batch_revision("tb-1") == first
        assert uow.tickets.assert_current_revision("tb-1", 1) == first
        with pytest.raises(OptimisticConcurrencyError, match="expected 0"):
            uow.tickets.assert_current_revision("tb-1", 0)
        uow.tickets.insert_batch_revision(second)

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.current_batch_revision("tb-1") == second
        assert uow.tickets.batch_history("tb-1") == [first, second]
        assert uow.tickets.count_batches() == 1


def test_repository_round_trips_artifact_confirmation_and_placement(
    tmp_path: Path,
) -> None:
    kernel, _report, action_id, source_artifact_id = _kernel(tmp_path)
    revision = _revision(action_id, source_artifact_id)
    ticket_artifact = AuditedTicketArtifactRow(
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
        approved_at=AT,
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
        issued_at=AT,
        expires_at="2026-08-24T10:05:00+00:00",
        consumed_at=None,
        consumed_by_action_id=None,
    )

    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.tickets.insert_batch_revision(revision)
        uow.tickets.insert_ticket_artifact(ticket_artifact)
        uow.tickets.insert_confirmation(confirmation)
        assert uow.tickets.ticket_artifacts_for_revision("tbr-1") == [ticket_artifact]
        assert uow.tickets.ticket_artifact("tat-1") == ticket_artifact
        assert uow.tickets.confirmation("tc-1") == confirmation
        uow.tickets.consume_confirmation("tc-1", AT, action_id)

    with OntologyUnitOfWork(kernel.engine) as uow:
        consumed = uow.tickets.confirmation("tc-1")
        assert consumed is not None and consumed.consumed_at == AT
        uow.finance.insert_ticket(
            TicketRow(
                ticket_id="tk-1",
                channel="jczq",
                proposal_id=None,
                approved_at=AT,
                status="approved",
                structure="single",
                total_stake=100.0,
                currency="CNY",
                account_id="acct-jczq",
            )
        )
        placement = TicketPlacementRow(
            ticket_placement_id="tpl-1",
            ticket_artifact_id="tat-1",
            ticket_id="tk-1",
            placement_mode="manual",
            external_reference="manual-001",
            receipt_artifact_id=None,
            receipt_retrieval_id=None,
            placed_at=AT,
            action_id=action_id,
        )
        uow.tickets.insert_placement(placement)
        assert uow.tickets.placement_for_artifact("tat-1") == placement
        assert uow.tickets.count_artifacts() == 1
        assert uow.tickets.count_placements() == 1


def test_schema_declares_confirmation_and_placement_uniqueness() -> None:
    confirmation_uniques = {
        tuple(constraint.columns.keys())
        for constraint in schema_tickets.ticket_confirmation_challenges.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    placement_uniques = {
        tuple(constraint.columns.keys())
        for constraint in schema_tickets.ticket_placements.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("nonce_hash",) in confirmation_uniques
    assert ("ticket_artifact_id",) in placement_uniques
    assert ("ticket_id",) in placement_uniques
    assert ("action_id",) in placement_uniques
