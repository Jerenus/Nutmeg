import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.protected_ticket_actions import (
    ConfirmTicketPlacementRequest,
    IssueTicketConfirmationRequest,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.tickets import TicketWorkbenchRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from tests.ontology.test_protected_ticket_actions import (
    AT,
    PRIOR,
    _approve_request,
    _create_request,
    _created_row,
    _leg,
    _setup,
)

RECEIPT = b"manual receipt fixture"


def _approved(tmp_path: Path):
    kernel, forecast_id = _setup(tmp_path)
    created = kernel.protected_tickets.create_ticket_batch(
        _create_request(_leg(forecast_id))
    )
    draft = _created_row(kernel, created)
    assert draft is not None
    approved = kernel.protected_tickets.approve_ticket_batch(
        _approve_request(draft.ticket_batch_id, 1)
    )
    revision = _created_row(kernel, approved)
    assert revision is not None
    artifact_id = next(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        artifact = uow.tickets.ticket_artifact(artifact_id)
    assert artifact is not None
    return kernel, forecast_id, artifact


def _issue(kernel, artifact_id: str, *, role=ActorRole.JUDGE_OPERATOR, key="m4:issue"):
    return kernel.protected_tickets.issue_ticket_confirmation(
        IssueTicketConfirmationRequest(
            ticket_artifact_id=artifact_id,
            actor_id="operator:owner" if role is ActorRole.JUDGE_OPERATOR else "model:test",
            actor_role=role,
            idempotency_key=key,
            requested_at=AT,
        )
    )


def _confirm(artifact, issued, **changes):
    values = {
        "ticket_artifact_id": artifact.ticket_artifact_id,
        "confirmation_id": issued.confirmation_id,
        "nonce": issued.nonce,
        "ticket_hash": artifact.ticket_hash,
        "amount": artifact.amount,
        "currency": artifact.currency,
        "channel": artifact.channel,
        "placement_mode": "manual",
        "external_reference": "manual-001",
        "receipt_content": RECEIPT,
        "receipt_content_type": "text/plain",
        "actor_id": "operator:owner",
        "actor_role": ActorRole.JUDGE_OPERATOR,
        "idempotency_key": "m4:confirm",
        "requested_at": AT,
    }
    values.update(changes)
    return ConfirmTicketPlacementRequest(**values)


def test_issue_returns_nonce_once_but_persists_only_digest(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)

    issued = _issue(kernel, artifact.ticket_artifact_id)

    assert issued.outcome.status is ActionStatus.COMMITTED
    assert issued.nonce is not None and len(issued.nonce) >= 32
    with OntologyUnitOfWork(kernel.engine) as uow:
        challenge = uow.tickets.confirmation(issued.confirmation_id)
        payload = uow.connection.execute(
            select(schema.actions.c.payload_json).where(
                schema.actions.c.action_id == issued.outcome.action_id
            )
        ).scalar_one()
    assert challenge is not None
    assert challenge.nonce_hash == hashlib.sha256(issued.nonce.encode()).hexdigest()
    assert issued.nonce not in payload

    replayed = _issue(kernel, artifact.ticket_artifact_id)
    assert replayed.outcome.action_id == issued.outcome.action_id
    assert replayed.nonce is None


def test_ai_cannot_issue_or_confirm_ticket(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    denied_issue = _issue(
        kernel, artifact.ticket_artifact_id, role=ActorRole.AI_ANALYST, key="m4:issue:ai"
    )
    assert denied_issue.outcome.status is ActionStatus.REJECTED

    issued = _issue(kernel, artifact.ticket_artifact_id)
    denied_confirm = kernel.protected_tickets.confirm_ticket_placement(
        _confirm(
            artifact,
            issued,
            actor_id="model:test",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="m4:confirm:ai",
        )
    )
    assert denied_confirm.status is ActionStatus.REJECTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 0
        assert uow.finance.ledger_balance("acct-jczq") == 0.0


def test_manual_confirmation_atomically_books_ticket_receipt_and_debit(
    tmp_path: Path,
) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)

    outcome = kernel.protected_tickets.confirm_ticket_placement(
        _confirm(artifact, issued)
    )

    assert outcome.status is ActionStatus.COMMITTED
    refs = {ref.object_type: ref.object_id for ref in outcome.result_refs}
    assert {"ticket", "cash_transaction", "ticket_placement", "source_artifact"} <= refs.keys()
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 1
        assert uow.finance.ledger_balance("acct-jczq") == -artifact.amount
        placement = uow.tickets.placement_for_artifact(artifact.ticket_artifact_id)
        challenge = uow.tickets.confirmation(issued.confirmation_id)
    assert placement is not None
    assert placement.ticket_id == refs["ticket"]
    assert placement.receipt_artifact_id == refs["source_artifact"]
    assert challenge is not None and challenge.consumed_at is not None
    digest = placement.receipt_artifact_id.removeprefix("sha256:")
    assert (
        kernel.paths.artifacts / "sha256" / digest[:2] / digest
    ).read_bytes() == RECEIPT


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"nonce": "wrong-nonce"}, "nonce"),
        ({"ticket_hash": "wrong-hash"}, "binding"),
        ({"amount": 99.0}, "binding"),
        ({"channel": "other"}, "binding"),
    ],
)
def test_confirmation_binding_mismatch_never_books(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)

    with pytest.raises(ValueError, match=message):
        kernel.protected_tickets.confirm_ticket_placement(
            _confirm(artifact, issued, idempotency_key=f"m4:mismatch:{message}", **changes)
        )

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 0
        assert uow.finance.ledger_balance("acct-jczq") == 0.0


def test_expired_confirmation_never_books(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)

    with pytest.raises(ValueError, match="expired"):
        kernel.protected_tickets.confirm_ticket_placement(
            _confirm(
                artifact,
                issued,
                idempotency_key="m4:confirm:expired",
                requested_at=AT + timedelta(minutes=6),
            )
        )

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 0


def test_duplicate_confirmation_replays_once_and_consumed_nonce_cannot_rebook(
    tmp_path: Path,
) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)
    request = _confirm(artifact, issued)

    first = kernel.protected_tickets.confirm_ticket_placement(request)
    replay = kernel.protected_tickets.confirm_ticket_placement(request)

    assert replay.action_id == first.action_id
    with pytest.raises(ValueError, match="consumed|placed"):
        kernel.protected_tickets.confirm_ticket_placement(
            replace(request, idempotency_key="m4:confirm:different-key")
        )
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 1
        assert uow.finance.ledger_balance("acct-jczq") == -artifact.amount


def test_confirmation_survives_process_restart(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)
    restarted = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))

    outcome = restarted.protected_tickets.confirm_ticket_placement(
        _confirm(artifact, issued, idempotency_key="m4:confirm:restart")
    )

    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(restarted.engine) as uow:
        assert uow.finance.count_tickets() == 1


def test_new_forecast_after_approval_blocks_confirmation(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)
    kernel.forecast_actions.revise_forecast(
        CommitForecastRequest(
            match_id="match-1",
            market_definition_id="md-had",
            decision_session_id=None,
            prior_distribution=PRIOR,
            belief_distribution=PRIOR,
            factors=[],
            commitment_tier="judged",
            evidence_bundle_id=None,
            prior_snapshot_id=None,
            falsifier=None,
            actor_id="operator:owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m4:forecast:revise",
            requested_at=AT,
            expected_current_revision_no=1,
        )
    )

    with pytest.raises(ValueError, match="committed revision"):
        kernel.protected_tickets.confirm_ticket_placement(
            _confirm(
                artifact,
                issued,
                idempotency_key="m4:confirm:stale-forecast",
            )
        )

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 0


def test_database_failure_rolls_back_booking_and_challenge_consumption(
    tmp_path: Path, monkeypatch
) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)

    def fail_placement(*_args, **_kwargs):
        raise RuntimeError("placement persistence failed")

    monkeypatch.setattr(TicketWorkbenchRepository, "insert_placement", fail_placement)
    with pytest.raises(RuntimeError, match="placement persistence failed"):
        kernel.protected_tickets.confirm_ticket_placement(
            _confirm(
                artifact,
                issued,
                idempotency_key="m4:confirm:rollback",
            )
        )

    with OntologyUnitOfWork(kernel.engine) as uow:
        challenge = uow.tickets.confirmation(issued.confirmation_id)
        assert uow.finance.count_tickets() == 0
        assert uow.finance.ledger_balance("acct-jczq") == 0.0
        assert uow.tickets.count_placements() == 0
    assert challenge is not None and challenge.consumed_at is None


def test_manual_confirmation_requires_receipt_and_connector_is_disabled(
    tmp_path: Path,
) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)

    with pytest.raises(ValueError, match="receipt"):
        kernel.protected_tickets.confirm_ticket_placement(
            _confirm(
                artifact,
                issued,
                receipt_content=b"",
                idempotency_key="m4:confirm:no-receipt",
            )
        )
    with pytest.raises(ValueError, match="connector.*unavailable"):
        kernel.protected_tickets.confirm_ticket_placement(
            _confirm(
                artifact,
                issued,
                placement_mode="connector",
                idempotency_key="m4:confirm:connector",
            )
        )
