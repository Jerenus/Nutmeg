from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text

from nutmeg.ontology.actions.models import ActionCommand, ActorRole, ObjectRef
from nutmeg.ontology.actions.protected_ticket_actions import (
    ApproveOperatorTicketBatchRequest,
    CreateOperatorTicketBatchRequest,
    CurrentOperatorCandidateAudit,
    ProtectedTicketActions,
)
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.operator.decision_actions import (
    FreezeJudgmentPrescriptionRequest,
    SelectTicketCandidateRequest,
)
from nutmeg.ontology.operator.result_actions import OperatorResultActions
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.migrations import (
    MIGRATIONS,
    migration_status,
    run_migrations,
)
from nutmeg.ontology.repository.tickets import ConfirmationChallengeRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.operator.test_candidate_actions import (
    CandidateFixture,
    _generate,
    _generation_request,
)
from tests.ontology.operator.test_judgment_actions import (
    AT,
    _create_baseline_and_envelope,
    _judgment_request,
)
from tests.ontology.operator.test_judgment_actions import (
    _fixture as _judgment_fixture,
)

CONFIRMATION_TABLES = {
    "operator_ticket_notes",
    "operator_ticket_note_legs",
    "operator_placement_cash_links",
    "operator_telegram_owner_heartbeats",
    "operator_telegram_callback_attestations",
}


def _columns(engine, table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspect(engine).get_columns(table_name)
    }


def _unique_column_sets(engine, table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(str(column) for column in constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints(table_name)
    }


def _table_sql(engine, table_name: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'table' AND name = :table_name"
                ),
                {"table_name": table_name},
            ).scalar_one()
        )


def test_migration_23_preserves_v22_challenge_shape_and_adds_confirmation_storage(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "upgrade.db")
    run_migrations(engine, MIGRATIONS[:22])
    v22_challenge_columns = _columns(
        engine,
        "operator_confirmation_challenge_revisions",
    )
    assert migration_status(engine).current_version == 22
    assert CONFIRMATION_TABLES.isdisjoint(inspect(engine).get_table_names())
    assert "legacy_expires_at" not in v22_challenge_columns

    run_migrations(engine)

    assert migration_status(engine).current_version == 23
    assert CONFIRMATION_TABLES <= set(inspect(engine).get_table_names())
    assert _columns(engine, "operator_confirmation_challenge_revisions") == (
        v22_challenge_columns | {"legacy_expires_at"}
    )


def test_migration_23_declares_normalized_note_cash_and_owner_contracts(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "shape.db")
    run_migrations(engine)

    assert _columns(engine, "operator_ticket_notes") == {
        "ticket_note_id",
        "ticket_id",
        "ticket_artifact_id",
        "note_index",
        "ticket_kind",
        "structure_code",
        "group_code",
        "currency",
        "unit_stake_minor",
        "unit_count",
        "stake_minor",
        "composition_hash",
        "fixed_prize_policy_revision_id",
        "action_id",
        "created_at",
    }
    assert _columns(engine, "operator_ticket_note_legs") == {
        "ticket_note_leg_id",
        "ticket_note_id",
        "leg_index",
        "official_offer_revision_id",
        "match_id",
        "market_definition_id",
        "selection_code",
        "quote_id",
        "booked_decimal_odds",
        "settlement_parameter_decimal",
        "fixed_prize_policy_revision_id",
        "action_id",
    }
    assert _columns(engine, "operator_placement_cash_links") == {
        "placement_cash_link_id",
        "ticket_id",
        "transaction_id",
        "stake_minor",
        "currency",
        "action_id",
        "created_at",
    }
    assert _columns(engine, "operator_telegram_owner_heartbeats") == {
        "telegram_owner_heartbeat_id",
        "account_id",
        "owner_instance_id",
        "transport_label",
        "owner_mode",
        "router_version",
        "heartbeat_sequence",
        "observed_at",
        "lease_expires_at",
        "registration_action_id",
    }
    assert _columns(engine, "operator_telegram_callback_attestations") == {
        "telegram_callback_attestation_id",
        "account_id",
        "owner_instance_id",
        "callback_query_id",
        "sender_id",
        "chat_id",
        "message_id",
        "namespace",
        "callback_data_hash",
        "server_ingress_at",
        "owner_heartbeat_id",
        "source_artifact_id",
        "source_artifact_retrieval_id",
        "action_id",
        "created_at",
    }
    assert {"ticket_kind", "stake_minor", "fixed_prize_policy_revision_id"} <= (
        _columns(engine, "tickets")
    )
    assert {"amount_minor", "currency"} <= _columns(engine, "cash_transactions")
    assert {
        ("ticket_id", "note_index"),
        ("ticket_id", "composition_hash"),
    } <= _unique_column_sets(engine, "operator_ticket_notes")
    assert ("ticket_note_id", "leg_index") in _unique_column_sets(
        engine,
        "operator_ticket_note_legs",
    )
    assert ("ticket_id",) in _unique_column_sets(
        engine,
        "operator_placement_cash_links",
    )
    assert ("transaction_id",) in _unique_column_sets(
        engine,
        "operator_placement_cash_links",
    )
    assert ("account_id", "owner_instance_id") in _unique_column_sets(
        engine,
        "operator_telegram_owner_heartbeats",
    )
    assert ("account_id", "callback_query_id") in _unique_column_sets(
        engine,
        "operator_telegram_callback_attestations",
    )

    note_sql = _table_sql(engine, "operator_ticket_notes")
    leg_sql = _table_sql(engine, "operator_ticket_note_legs")
    assert "stake_minor = unit_stake_minor * unit_count" in note_sql
    assert "ticket_kind IN ('jczq_pass', 'sfc', 'renjiu')" in note_sql
    assert "booked_decimal_odds" in leg_sql
    assert "fixed_prize_policy_revision_id" in leg_sql


def test_confirmation_owner_registration_is_deterministic_system_only(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "permissions.db")
    run_migrations(engine)

    with engine.connect() as connection:
        roles = tuple(
            connection.execute(
                select(schema.action_permissions.c.actor_role).where(
                    schema.action_permissions.c.action_type
                    == "register_telegram_update_owner"
                )
            ).scalars()
        )

    assert roles == ("deterministic_system",)


def _ready_v21_candidate(tmp_path: Path) -> CandidateFixture:
    judgment = _judgment_fixture(tmp_path, migrations=MIGRATIONS[:21])
    baseline_id, envelope_id = _create_baseline_and_envelope(judgment)
    committed = judgment.decision_actions.commit_operator_match_judgment(
        _judgment_request(judgment, baseline_id, envelope_id)
    )
    judgment_id = next(
        ref.object_id
        for ref in committed.result_refs
        if ref.object_type == "operator_match_judgment_revision"
    )
    prescription = judgment.decision_actions.freeze_judgment_prescription(
        FreezeJudgmentPrescriptionRequest(
            task_evidence_bundle_revision_id=judgment.task_bundle_revision_id,
            market_prior_baseline_revision_id=baseline_id,
            baseline_envelope_revision_id=envelope_id,
            work_item_id="jczq:2026-09-04:wave:current",
            judgment_revision_ids=(judgment_id,),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="migration-23:prescription",
            requested_at=AT + timedelta(seconds=5),
            expected_current_revision_no=0,
        )
    )
    return CandidateFixture(
        judgment=judgment,
        result_actions=OperatorResultActions(judgment.action_service),
        baseline_id=baseline_id,
        envelope_id=envelope_id,
        prescription_id=prescription.result_refs[0].object_id,
    )


def _legacy_challenge_upgrade_fixture(tmp_path: Path):
    fixture = _ready_v21_candidate(tmp_path)
    generated_request = fixture.judgment.decision_actions.request_candidate_generation(
        _generation_request(fixture, key="migration-23:generation")
    )
    _generate(fixture, request_id=generated_request.result_refs[0].object_id)
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        candidate_set = uow.operator_result.current_candidate_set(
            task_family_id="jczq:2026-09-04",
            work_item_id="jczq:2026-09-04:wave:current",
            set_kind="judgment_bound",
        )
        assert candidate_set is not None
        candidate = uow.operator_result.candidates_for_set(
            candidate_set.candidate_set_revision_id
        )[0]
        uow.finance.ensure_account(CashAccountRow("acct-jczq", "jczq", "CNY", "active"))
    selected = fixture.judgment.decision_actions.select_ticket_candidate(
        SelectTicketCandidateRequest(
            candidate_set_revision_id=candidate_set.candidate_set_revision_id,
            candidate_revision_id=candidate.candidate_revision_id,
            reason="Jun selected the migration replay candidate.",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="migration-23:selection",
            requested_at=AT + timedelta(seconds=9),
            expected_current_revision_no=0,
        )
    )
    run_migrations(fixture.judgment.engine, MIGRATIONS[:22])
    protected = ProtectedTicketActions(
        fixture.judgment.action_service,
        ContentAddressedArtifactStore(tmp_path / "artifacts"),
        operator_decisions=fixture.judgment.decision_actions,
        operator_candidate_auditor=lambda _uow, _selected: CurrentOperatorCandidateAudit(
            policy_version="operator-candidate-audit-v1",
            completed_audit_kinds=(
                "legs",
                "prescription_difference",
                "budget",
                "deployment",
            ),
            findings=(),
        ),
    )
    created = protected.create_operator_ticket_batch(
        CreateOperatorTicketBatchRequest(
            candidate_selection_id=selected.result_refs[0].object_id,
            account_id="acct-jczq",
            run_date="2026-09-04",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="migration-23:create",
            requested_at=AT + timedelta(seconds=10),
        )
    )
    batch_revision_id = next(
        ref.object_id
        for ref in created.result_refs
        if ref.object_type == "ticket_batch_revision"
    )
    approved = protected.approve_operator_ticket_batch(
        ApproveOperatorTicketBatchRequest(
            ticket_batch_revision_id=batch_revision_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="migration-23:approve",
            requested_at=AT + timedelta(seconds=11),
        )
    )
    artifact_id = next(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    with OntologyUnitOfWork(fixture.judgment.engine) as uow:
        artifact = uow.tickets.ticket_artifact(artifact_id)
        binding = uow.tickets.protected_artifact_binding(artifact_id)
        assert artifact is not None
        assert binding is not None

    for index in (1, 2):
        confirmation_id = f"legacy-confirmation-{index}"
        issued_at = AT + timedelta(minutes=index)
        command = ActionCommand.create(
            action_type="issue_ticket_confirmation",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"migration-23:challenge:{index}",
            requested_at=issued_at,
            payload={"ticket_artifact_id": artifact_id},
        )

        def handler(uow, _action, *, current_index=index, current_id=confirmation_id):
            uow.tickets.insert_confirmation(
                ConfirmationChallengeRow(
                    confirmation_id=current_id,
                    ticket_artifact_id=artifact_id,
                    nonce_hash=str(current_index) * 64,
                    ticket_hash=artifact.ticket_hash,
                    amount=artifact.amount,
                    currency=artifact.currency,
                    channel=artifact.channel,
                    issued_at=(AT + timedelta(minutes=current_index)).isoformat(),
                    expires_at=(AT + timedelta(minutes=current_index + 5)).isoformat(),
                    consumed_at=None,
                    consumed_by_action_id=None,
                )
            )
            return (ObjectRef("ticket_confirmation", current_id),)

        fixture.judgment.action_service.execute(command, handler)
    return fixture.judgment.engine, artifact_id, binding.frozen_deadline_at


def test_migration_23_reconciles_legacy_challenges_into_stable_revisions(
    tmp_path: Path,
) -> None:
    engine, artifact_id, cutoff = _legacy_challenge_upgrade_fixture(tmp_path)

    report = run_migrations(engine)

    assert report.applied_versions == (23,)
    with engine.connect() as connection:
        revisions = connection.execute(
            text(
                "SELECT challenge_revision_id, challenge_family_id, "
                "legacy_confirmation_id, revision_no, supersedes_revision_id, "
                "effective_cutoff_at, legacy_expires_at "
                "FROM operator_confirmation_challenge_revisions "
                "WHERE ticket_artifact_id = :artifact_id ORDER BY revision_no"
            ),
            {"artifact_id": artifact_id},
        ).mappings().all()
        head = connection.execute(
            text(
                "SELECT challenge_revision_id, challenge_family_id, revision_no "
                "FROM operator_confirmation_challenge_heads "
                "WHERE ticket_artifact_id = :artifact_id"
            ),
            {"artifact_id": artifact_id},
        ).mappings().one()

    assert [row["legacy_confirmation_id"] for row in revisions] == [
        "legacy-confirmation-1",
        "legacy-confirmation-2",
    ]
    assert [row["revision_no"] for row in revisions] == [1, 2]
    assert revisions[0]["challenge_family_id"] == revisions[1]["challenge_family_id"]
    assert revisions[1]["supersedes_revision_id"] == revisions[0][
        "challenge_revision_id"
    ]
    assert {row["effective_cutoff_at"] for row in revisions} == {cutoff}
    assert [row["legacy_expires_at"] for row in revisions] == [
        (AT + timedelta(minutes=6)).isoformat(),
        (AT + timedelta(minutes=7)).isoformat(),
    ]
    assert head == {
        "challenge_revision_id": revisions[1]["challenge_revision_id"],
        "challenge_family_id": revisions[1]["challenge_family_id"],
        "revision_no": 2,
    }
    assert run_migrations(engine).applied_versions == ()


def test_migration_23_aborts_without_discarding_conflicting_legacy_rows(
    tmp_path: Path,
) -> None:
    engine, _artifact_id, _cutoff = _legacy_challenge_upgrade_fixture(tmp_path)
    with engine.begin() as connection:
        action_id = connection.scalar(
            text(
                "SELECT action_id FROM actions "
                "WHERE idempotency_key = 'migration-23:challenge:1'"
            )
        )
        connection.execute(
            text(
                "UPDATE ticket_confirmation_challenges "
                "SET consumed_at = :at, consumed_by_action_id = :action_id"
            ),
            {"at": (AT + timedelta(minutes=3)).isoformat(), "action_id": action_id},
        )

    with pytest.raises(ValueError, match="legacy_confirmation_conflict.*more than one"):
        run_migrations(engine)

    assert migration_status(engine).current_version == 22
    assert "legacy_expires_at" not in _columns(
        engine,
        "operator_confirmation_challenge_revisions",
    )
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM ticket_confirmation_challenges")
        ) == 2
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_confirmation_challenge_revisions")
        ) == 0
