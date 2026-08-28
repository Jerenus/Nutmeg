from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.protected_ticket_actions import MarkTicketShadowRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.test_protected_ticket_actions import AT
from tests.ontology.test_ticket_confirmation import _approved, _confirm, _issue


def _shadow_request(artifact, issued, **changes) -> MarkTicketShadowRequest:
    values = {
        "ticket_artifact_id": artifact.ticket_artifact_id,
        "confirmation_id": issued.confirmation_id,
        "reason": "deadline_unconfirmed",
        "actor_id": "system:telegram-confirmation",
        "actor_role": ActorRole.DETERMINISTIC_SYSTEM,
        "idempotency_key": "telegram:shadow:artifact",
        "requested_at": AT + timedelta(hours=2, minutes=1),
    }
    values.update(changes)
    return MarkTicketShadowRequest(**values)


def test_shadow_rejects_before_deadline(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)

    with pytest.raises(ValueError, match="deadline has not passed"):
        kernel.protected_tickets.mark_ticket_shadow(
            _shadow_request(artifact, issued, requested_at=AT + timedelta(minutes=6))
        )


def test_shadow_after_deadline_records_no_ticket_or_cash(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)

    outcome = kernel.protected_tickets.mark_ticket_shadow(
        _shadow_request(artifact, issued)
    )

    assert outcome.status is ActionStatus.COMMITTED
    assert outcome.result_refs[0].object_type == "ticket_shadow"
    with OntologyUnitOfWork(kernel.engine) as uow:
        shadow = uow.tickets.shadow_for_artifact(artifact.ticket_artifact_id)
        assert uow.finance.count_tickets() == 0
        assert uow.finance.ledger_balance("acct-jczq") == 0.0
    assert shadow is not None
    assert shadow.reason == "deadline_unconfirmed"
    assert shadow.confirmation_id == issued.confirmation_id


@pytest.mark.parametrize("role", [ActorRole.JUDGE_OPERATOR, ActorRole.AI_ANALYST])
def test_only_deterministic_system_can_mark_shadow(tmp_path: Path, role: ActorRole) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)

    outcome = kernel.protected_tickets.mark_ticket_shadow(
        _shadow_request(
            artifact,
            issued,
            actor_id="operator:test" if role is ActorRole.JUDGE_OPERATOR else "model:test",
            actor_role=role,
            idempotency_key=f"telegram:shadow:denied:{role.value}",
        )
    )

    assert outcome.status is ActionStatus.REJECTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.shadow_for_artifact(artifact.ticket_artifact_id) is None


def test_placed_ticket_cannot_be_marked_shadow(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)
    confirmed = kernel.protected_tickets.confirm_ticket_placement(
        _confirm(artifact, issued)
    )
    assert confirmed.status is ActionStatus.COMMITTED

    with pytest.raises(ValueError, match="already placed"):
        kernel.protected_tickets.mark_ticket_shadow(
            _shadow_request(artifact, issued)
        )


def test_shadow_replays_and_different_key_does_not_duplicate(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    issued = _issue(kernel, artifact.ticket_artifact_id)
    request = _shadow_request(artifact, issued)

    first = kernel.protected_tickets.mark_ticket_shadow(request)
    replay = kernel.protected_tickets.mark_ticket_shadow(request)
    second_action = kernel.protected_tickets.mark_ticket_shadow(
        replace(request, idempotency_key="telegram:shadow:artifact:retry")
    )

    assert replay.action_id == first.action_id
    assert second_action.action_id != first.action_id
    assert second_action.result_refs == first.result_refs


def test_due_shadow_candidates_require_challenge_deadline_and_no_shadow(
    tmp_path: Path,
) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    deadline = artifact.deadline_at

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.due_shadow_candidates(deadline) == []

    issued = _issue(kernel, artifact.ticket_artifact_id)
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.due_shadow_candidates(
            (AT + timedelta(hours=1)).isoformat()
        ) == []
        assert uow.tickets.due_shadow_candidates(deadline) == [
            (artifact.ticket_artifact_id, issued.confirmation_id)
        ]

    kernel.protected_tickets.mark_ticket_shadow(
        _shadow_request(artifact, issued)
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.tickets.due_shadow_candidates(deadline) == []
