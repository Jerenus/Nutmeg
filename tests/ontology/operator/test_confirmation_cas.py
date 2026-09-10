from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionStatus,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.protected_ticket_actions import (
    ConfirmTicketPlacementRequest,
    IssueTicketConfirmationRequest,
    ProtectedTicketActions,
    TelegramCallbackAttestationInput,
)
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.operator.confirmation import (
    ArtifactTerminalKind,
    ArtifactTerminalReason,
    consume_artifact_terminal,
)
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository import schema_tickets as st
from nutmeg.ontology.repository.operator_result import OperatorResultRepository
from nutmeg.ontology.repository.tickets import TicketWorkbenchRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.services.telegram_ticket_confirmation import (
    TelegramOwnerHeartbeatService,
)
from tests.ontology.operator.test_candidate_actions import _candidate
from tests.ontology.operator.test_no_ticket_actions import (
    AT,
    _artifact_fixture,
    _clean_candidate_audit,
    _issue_challenge,
    _request,
)


def _consume(
    fixture,
    *,
    key: str,
    at,
    kind: ArtifactTerminalKind,
    reason: ArtifactTerminalReason,
    challenge_revision_id: str | None = None,
    expected_challenge_revision: int | None = None,
):
    command = ActionCommand.create(
        action_type=(
            "confirm_ticket_placement"
            if kind is ArtifactTerminalKind.PLACED
            else "mark_ticket_shadow"
        ),
        actor_id=(
            "jun" if kind is ArtifactTerminalKind.PLACED else "system:confirmation-deadline"
        ),
        actor_role=(
            ActorRole.JUDGE_OPERATOR
            if kind is ArtifactTerminalKind.PLACED
            else ActorRole.DETERMINISTIC_SYSTEM
        ),
        idempotency_key=key,
        requested_at=at,
        payload={"ticket_artifact_id": fixture.artifact_id},
    )
    captured = {}

    def handler(uow, action) -> tuple[ObjectRef, ...]:
        transition = consume_artifact_terminal(
            uow,
            ticket_artifact_id=fixture.artifact_id,
            challenge_revision_id=challenge_revision_id,
            expected_challenge_revision=expected_challenge_revision,
            terminal_kind=kind,
            terminal_reason=reason,
            action_id=action.action_id,
            ingress_at=at,
        )
        captured["transition"] = transition
        return (
            ObjectRef(
                "artifact_terminal_receipt",
                transition.receipt.artifact_terminal_receipt_id,
            ),
        )

    outcome = fixture.action_service.execute(
        command,
        handler,
        acquire_write_lock=True,
    )
    assert outcome.status is ActionStatus.COMMITTED
    return captured["transition"]


def _protected(fixture, tmp_path: Path) -> ProtectedTicketActions:
    return ProtectedTicketActions(
        fixture.action_service,
        ContentAddressedArtifactStore(tmp_path / "ticket-artifacts"),
        operator_decisions=fixture.actions,
        operator_candidate_auditor=_clean_candidate_audit,
    )


def _issue(protected, fixture, *, key: str):
    return protected.issue_ticket_confirmation(
        IssueTicketConfirmationRequest(
            ticket_artifact_id=fixture.artifact_id,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=key,
            requested_at=AT + timedelta(minutes=2),
        )
    )


def _attestation(fixture, *, callback_id: str, at) -> TelegramCallbackAttestationInput:
    owner = TelegramOwnerHeartbeatService(
        action_service=fixture.action_service,
        account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        transport_label="openclaw-telegram",
        owner_mode="openclaw",
        router_version="ntc-v1",
        lease_duration=timedelta(seconds=90),
    )
    heartbeat = owner.pulse(observed_at=at - timedelta(seconds=30))
    return TelegramCallbackAttestationInput(
        account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        callback_query_id=callback_id,
        sender_id="222",
        chat_id="111",
        message_id="7",
        namespace="ntc",
        callback_data_hash="a" * 64,
        server_ingress_at=at,
        owner_heartbeat_id=heartbeat.telegram_owner_heartbeat_id,
        bridge_received_at=at + timedelta(seconds=1),
        heartbeat_lease_expires_at=at + timedelta(seconds=91),
    )


def test_terminal_cas_requires_the_current_expected_challenge_revision(tmp_path) -> None:
    fixture = _artifact_fixture(tmp_path)
    challenge_id = _issue_challenge(fixture)

    with pytest.raises(ValueError, match="challenge revision"):
        _consume(
            fixture,
            key="confirmation-cas:stale-revision",
            at=AT + timedelta(minutes=3),
            kind=ArtifactTerminalKind.PLACED,
            reason=ArtifactTerminalReason.ACTUAL_PLACEMENT_CONFIRMED,
            challenge_revision_id=challenge_id,
            expected_challenge_revision=2,
        )

    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.tickets.artifact_terminal_receipt(fixture.artifact_id) is None
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
    assert head is not None
    assert head.revision_no == 1


def test_exact_cutoff_without_challenge_terminalizes_as_not_requested(tmp_path) -> None:
    fixture = _artifact_fixture(tmp_path)

    transition = _consume(
        fixture,
        key="confirmation-cas:no-challenge-cutoff",
        at=fixture.cutoff,
        kind=ArtifactTerminalKind.SHADOW,
        reason=ArtifactTerminalReason.CONFIRMATION_NOT_REQUESTED,
    )

    assert transition.created is True
    assert transition.requested_transition_won is True
    assert transition.receipt.challenge_revision_id is None
    assert transition.receipt.terminal_kind == "shadow"
    assert transition.receipt.terminal_reason == "confirmation_not_requested"


def test_callback_one_microsecond_before_cutoff_wins_then_scanner_replays_receipt(
    tmp_path,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    challenge_id = _issue_challenge(fixture)

    placement = _consume(
        fixture,
        key="confirmation-cas:callback-wins",
        at=fixture.cutoff - timedelta(microseconds=1),
        kind=ArtifactTerminalKind.PLACED,
        reason=ArtifactTerminalReason.ACTUAL_PLACEMENT_CONFIRMED,
        challenge_revision_id=challenge_id,
        expected_challenge_revision=1,
    )
    scanner = _consume(
        fixture,
        key="confirmation-cas:scanner-loses",
        at=fixture.cutoff,
        kind=ArtifactTerminalKind.SHADOW,
        reason=ArtifactTerminalReason.DEADLINE_UNCONFIRMED,
        challenge_revision_id=challenge_id,
        expected_challenge_revision=1,
    )

    assert placement.created is True
    assert placement.requested_transition_won is True
    assert scanner.created is False
    assert scanner.requested_transition_won is False
    assert scanner.receipt == placement.receipt
    with fixture.engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM operator_artifact_terminal_receipts")
        ) == 1


def test_callback_at_cutoff_loses_to_deadline_even_before_scanner_runs(tmp_path) -> None:
    fixture = _artifact_fixture(tmp_path)
    challenge_id = _issue_challenge(fixture)

    transition = _consume(
        fixture,
        key="confirmation-cas:callback-at-cutoff",
        at=fixture.cutoff,
        kind=ArtifactTerminalKind.PLACED,
        reason=ArtifactTerminalReason.ACTUAL_PLACEMENT_CONFIRMED,
        challenge_revision_id=challenge_id,
        expected_challenge_revision=1,
    )

    assert transition.created is True
    assert transition.requested_transition_won is False
    assert transition.receipt.terminal_kind == "shadow"
    assert transition.receipt.terminal_reason == "deadline_unconfirmed"


def test_issue_uses_current_cutoff_and_reuses_one_open_challenge(tmp_path: Path) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)

    issued = _issue(protected, fixture, key="confirmation:issue:first")
    repeated = _issue(protected, fixture, key="confirmation:issue:again")

    assert issued.confirmation_id is not None
    assert issued.nonce is not None
    assert issued.expires_at == fixture.cutoff.isoformat()
    assert repeated.confirmation_id == issued.confirmation_id
    assert repeated.nonce is None
    assert repeated.expires_at == fixture.cutoff.isoformat()
    with OntologyUnitOfWork(fixture.engine) as uow:
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
        assert head is not None
        challenge = uow.tickets.confirmation_challenge_revision(
            head.challenge_revision_id
        )
        legacy_count = uow.connection.scalar(
            select(func.count()).select_from(st.ticket_confirmation_challenges)
        )
        revision_count = uow.connection.scalar(
            select(func.count()).select_from(
                st.operator_confirmation_challenge_revisions
            )
        )
    assert challenge is not None
    assert challenge.revision_no == 1
    assert challenge.effective_cutoff_at == fixture.cutoff.isoformat()
    assert legacy_count == 0
    assert revision_count == 1


def test_v2_callback_atomically_materializes_ticket_notes_and_minor_unit_ledger(
    tmp_path: Path,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:atomic:issue")
    assert issued.confirmation_id is not None
    assert issued.nonce is not None
    with OntologyUnitOfWork(fixture.engine) as uow:
        artifact = uow.tickets.ticket_artifact(fixture.artifact_id)
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
    assert artifact is not None
    assert head is not None

    outcome = protected.confirm_ticket_placement(
        ConfirmTicketPlacementRequest(
            ticket_artifact_id=fixture.artifact_id,
            confirmation_id=issued.confirmation_id,
            nonce=issued.nonce,
            ticket_hash=artifact.ticket_hash,
            amount=artifact.amount,
            currency=artifact.currency,
            channel=artifact.channel,
            placement_mode="manual",
            external_reference="telegram:callback-atomic",
            receipt_content=b'{"attestation":"actual_placement_confirmed"}',
            receipt_content_type="application/vnd.nutmeg.telegram-attestation+json",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="confirmation:atomic:callback",
            requested_at=AT + timedelta(minutes=3),
            expected_challenge_revision=head.revision_no,
            telegram_attestation=_attestation(
                fixture,
                callback_id="callback-atomic",
                at=AT + timedelta(minutes=3),
            ),
        )
    )

    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(fixture.engine) as uow:
        terminal = uow.tickets.artifact_terminal_receipt(fixture.artifact_id)
        placement = uow.tickets.placement_for_artifact(fixture.artifact_id)
        tickets = uow.connection.execute(select(sf.tickets)).mappings().all()
        notes = uow.connection.execute(select(sor.operator_ticket_notes)).mappings().all()
        note_legs = uow.connection.execute(
            select(sor.operator_ticket_note_legs)
        ).mappings().all()
        cash = uow.connection.execute(select(sf.cash_transactions)).mappings().all()
        links = uow.connection.execute(
            select(sor.operator_placement_cash_links)
        ).mappings().all()
    assert terminal is not None
    assert terminal.terminal_kind == "placed"
    assert terminal.terminal_reason == "actual_placement_confirmed"
    assert placement is not None
    assert len(tickets) == 1
    assert tickets[0]["ticket_kind"] == "jczq_pass"
    assert tickets[0]["stake_minor"] == 200
    assert len(notes) == 1
    assert len(note_legs) == 1
    assert len(cash) == 1
    assert cash[0]["amount_minor"] == -200
    assert cash[0]["currency"] == "CNY"
    assert len(links) == 1
    assert links[0]["stake_minor"] == 200


@pytest.mark.parametrize(
    ("repository_type", "method_name", "failure_label"),
    (
        (TicketWorkbenchRepository, "insert_placement", "after notes"),
        (
            OperatorResultRepository,
            "insert_telegram_callback_attestation",
            "after placement",
        ),
        (OperatorResultRepository, "insert_placement_cash_link", "after cash"),
    ),
)
def test_v2_callback_failure_rolls_back_terminal_ticket_notes_and_cash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repository_type: type,
    method_name: str,
    failure_label: str,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:rollback:issue")
    assert issued.confirmation_id is not None
    assert issued.nonce is not None
    with OntologyUnitOfWork(fixture.engine) as uow:
        artifact = uow.tickets.ticket_artifact(fixture.artifact_id)
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
    assert artifact is not None
    assert head is not None

    def fail_at_injection_point(*_args, **_kwargs):
        raise RuntimeError(f"injected failure {failure_label}")

    monkeypatch.setattr(
        repository_type,
        method_name,
        fail_at_injection_point,
    )
    with pytest.raises(RuntimeError, match=f"injected failure {failure_label}"):
        protected.confirm_ticket_placement(
            ConfirmTicketPlacementRequest(
                ticket_artifact_id=fixture.artifact_id,
                confirmation_id=issued.confirmation_id,
                nonce=issued.nonce,
                ticket_hash=artifact.ticket_hash,
                amount=artifact.amount,
                currency=artifact.currency,
                channel=artifact.channel,
                placement_mode="manual",
                external_reference="telegram:callback-rollback",
                receipt_content=b'{"attestation":"actual_placement_confirmed"}',
                receipt_content_type=(
                    "application/vnd.nutmeg.telegram-attestation+json"
                ),
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="confirmation:rollback:callback",
                requested_at=AT + timedelta(minutes=3),
                expected_challenge_revision=head.revision_no,
                telegram_attestation=_attestation(
                    fixture,
                    callback_id="callback-rollback",
                    at=AT + timedelta(minutes=3),
                ),
            )
        )

    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.tickets.artifact_terminal_receipt(fixture.artifact_id) is None
        assert uow.tickets.confirmation_challenge_head(fixture.artifact_id) is not None
        for table in (
            sf.tickets,
            sf.cash_transactions,
            st.ticket_placements,
            sor.operator_ticket_notes,
            sor.operator_ticket_note_legs,
            sor.operator_placement_cash_links,
        ):
            assert uow.connection.scalar(select(func.count()).select_from(table)) == 0


def test_v2_callback_reconciles_persisted_attestation_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _artifact_fixture(tmp_path)
    protected = _protected(fixture, tmp_path)
    issued = _issue(protected, fixture, key="confirmation:reconcile:issue")
    assert issued.confirmation_id is not None
    assert issued.nonce is not None
    with OntologyUnitOfWork(fixture.engine) as uow:
        artifact = uow.tickets.ticket_artifact(fixture.artifact_id)
        head = uow.tickets.confirmation_challenge_head(fixture.artifact_id)
    assert artifact is not None
    assert head is not None

    monkeypatch.setattr(
        OperatorResultRepository,
        "insert_telegram_callback_attestation",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="placement materialization did not reconcile"):
        protected.confirm_ticket_placement(
            ConfirmTicketPlacementRequest(
                ticket_artifact_id=fixture.artifact_id,
                confirmation_id=issued.confirmation_id,
                nonce=issued.nonce,
                ticket_hash=artifact.ticket_hash,
                amount=artifact.amount,
                currency=artifact.currency,
                channel=artifact.channel,
                placement_mode="manual",
                external_reference="telegram:callback-reconcile",
                receipt_content=b'{"attestation":"actual_placement_confirmed"}',
                receipt_content_type=(
                    "application/vnd.nutmeg.telegram-attestation+json"
                ),
                actor_id="jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="confirmation:reconcile:callback",
                requested_at=AT + timedelta(minutes=3),
                expected_challenge_revision=head.revision_no,
                telegram_attestation=_attestation(
                    fixture,
                    callback_id="callback-reconcile",
                    at=AT + timedelta(minutes=3),
                ),
            )
        )

    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.tickets.artifact_terminal_receipt(fixture.artifact_id) is None
        assert uow.tickets.confirmation_challenge_head(fixture.artifact_id) is not None
        for table in (
            sf.tickets,
            sf.cash_transactions,
            st.ticket_placements,
            sor.operator_ticket_notes,
            sor.operator_ticket_note_legs,
            sor.operator_placement_cash_links,
            sor.operator_telegram_callback_attestations,
        ):
            assert uow.connection.scalar(select(func.count()).select_from(table)) == 0


def test_two_artifact_batch_records_partial_placement_when_one_is_shadowed(
    tmp_path: Path,
) -> None:
    base_candidate = _candidate(
        set_kind="judgment_bound",
        content_hash="c" * 64,
    )
    first_ticket = base_candidate.tickets[0]
    second_ticket = replace(
        first_ticket,
        composition_hash="ticket-" + "d" * 64,
        legs=(
            replace(
                first_ticket.legs[0],
                selection_code="1",
                quote_id="quote-1",
                booked_decimal_odds="3.333333333333",
            ),
        ),
    )
    candidate = replace(
        base_candidate,
        tickets=(first_ticket, second_ticket),
        metrics=replace(
            base_candidate.metrics,
            ticket_count=2,
            distinct_note_count=2,
            paid_note_unit_count=2,
            stake_minor=400,
            probability_kind="any_ticket_all_required_legs",
        ),
    )
    fixture = _artifact_fixture(tmp_path, judgment_candidate=candidate)
    assert len(fixture.artifact_ids) == 2
    protected = _protected(fixture, tmp_path)

    placed_artifact_id, shadowed_artifact_id = fixture.artifact_ids
    placed_fixture = replace(fixture, artifact_id=placed_artifact_id)
    issued = _issue(
        protected,
        placed_fixture,
        key="confirmation:partial:issue",
    )
    assert issued.confirmation_id is not None
    assert issued.nonce is not None
    with OntologyUnitOfWork(fixture.engine) as uow:
        artifact = uow.tickets.ticket_artifact(placed_artifact_id)
        head = uow.tickets.confirmation_challenge_head(placed_artifact_id)
    assert artifact is not None
    assert head is not None
    confirmed = protected.confirm_ticket_placement(
        ConfirmTicketPlacementRequest(
            ticket_artifact_id=placed_artifact_id,
            confirmation_id=issued.confirmation_id,
            nonce=issued.nonce,
            ticket_hash=artifact.ticket_hash,
            amount=artifact.amount,
            currency=artifact.currency,
            channel=artifact.channel,
            placement_mode="manual",
            external_reference="telegram:callback-partial",
            receipt_content=b'{"attestation":"actual_placement_confirmed"}',
            receipt_content_type="application/vnd.nutmeg.telegram-attestation+json",
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="confirmation:partial:callback",
            requested_at=AT + timedelta(minutes=3),
            expected_challenge_revision=head.revision_no,
            telegram_attestation=_attestation(
                fixture,
                callback_id="callback-partial",
                at=AT + timedelta(minutes=3),
            ),
        )
    )
    assert confirmed.status is ActionStatus.COMMITTED

    context = fixture.actions.no_ticket_decision_context(
        task_family_id=fixture.context.task_family_id,
        lane=fixture.context.lane,
        business_key=fixture.context.business_key,
        work_item_id=fixture.context.work_item_id,
        as_of=AT + timedelta(minutes=4),
    )
    assert context.artifact_ids == (shadowed_artifact_id,)
    closed = fixture.actions.record_no_ticket(
        _request(
            fixture,
            key="confirmation:partial:no-ticket",
            requested_at=AT + timedelta(minutes=4),
            context=context,
        )
    )
    assert closed.status is ActionStatus.COMMITTED

    with OntologyUnitOfWork(fixture.engine) as uow:
        placed = uow.tickets.artifact_terminal_receipt(placed_artifact_id)
        shadowed = uow.tickets.artifact_terminal_receipt(shadowed_artifact_id)
        no_ticket = uow.operator_result.current_no_ticket_for_work_item(
            fixture.context.work_item_id
        )
        ticket_count = uow.connection.scalar(select(func.count()).select_from(sf.tickets))
        cash_count = uow.connection.scalar(
            select(func.count()).select_from(sf.cash_transactions)
        )
    assert placed is not None and placed.terminal_kind == "placed"
    assert shadowed is not None and shadowed.terminal_kind == "shadow"
    assert shadowed.terminal_reason == "human_no_ticket"
    assert no_ticket is not None
    assert no_ticket.deployment_outcome == "partially_placed"
    assert ticket_count == 1
    assert cash_count == 1
