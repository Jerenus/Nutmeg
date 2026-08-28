from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from nutmeg.interfaces.bot.telegram import TelegramBotRunner
from nutmeg.ontology.actions.models import ActionStatus
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_tickets as st
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.services.telegram_ticket_confirmation import (
    TelegramTicketConfirmationService,
)
from tests.ontology.test_protected_ticket_actions import (
    AT,
    _approve_request,
    _create_request,
    _created_row,
    _leg,
    _setup,
)


class _Client:
    def __init__(self) -> None:
        self.updates = []
        self.answers = []
        self.messages = []

    def get_updates(self, *, offset, timeout):
        updates, self.updates = self.updates, []
        return updates

    def answer_callback_query(self, *, callback_query_id, text):
        self.answers.append((callback_query_id, text))

    def send_message(self, *, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))
        return {"ok": True, "result": {"message_id": 8}}


class _NoMessageAdapter:
    def handle_message(self, text):
        raise AssertionError(f"protected callback reached message router: {text}")


def _artifact(kernel, forecast_id: str, index: int):
    created = kernel.protected_tickets.create_ticket_batch(
        _create_request(_leg(forecast_id), key=f"telegram:e2e:create:{index}")
    )
    draft = _created_row(kernel, created)
    assert draft is not None
    approved = kernel.protected_tickets.approve_ticket_batch(
        _approve_request(
            draft.ticket_batch_id,
            draft.revision_no,
            key=f"telegram:e2e:approve:{index}",
        )
    )
    assert approved.status is ActionStatus.COMMITTED
    artifact_id = next(
        ref.object_id
        for ref in approved.result_refs
        if ref.object_type == "audited_ticket_artifact"
    )
    with OntologyUnitOfWork(kernel.engine) as uow:
        artifact = uow.tickets.ticket_artifact(artifact_id)
    assert artifact is not None
    return artifact


def test_owner_callback_books_one_and_deadline_marks_sibling_shadow(
    tmp_path: Path,
) -> None:
    kernel, forecast_id = _setup(tmp_path)
    placed_artifact = _artifact(kernel, forecast_id, 1)
    shadow_artifact = _artifact(kernel, forecast_id, 2)
    client = _Client()
    clock = [AT]
    service = TelegramTicketConfirmationService(
        kernel=kernel,
        telegram_client=client,
        allowed_chat_ids={111},
        now_fn=lambda: clock[0],
    )
    placed = service.request_confirmation(
        ticket_artifact_id=placed_artifact.ticket_artifact_id,
        chat_id=111,
        dry_run=True,
        requested_at=AT,
    )
    service.request_confirmation(
        ticket_artifact_id=shadow_artifact.ticket_artifact_id,
        chat_id=111,
        dry_run=True,
        requested_at=AT,
    )
    runner = TelegramBotRunner(
        client=client,
        bot_adapter=_NoMessageAdapter(),
        allowed_chat_ids={111},
        confirmation_handler=service,
    )
    clock[0] = AT + timedelta(minutes=1)
    client.updates = [{
        "update_id": 1,
        "callback_query": {
            "id": "cb-e2e",
            "data": placed.callback_data,
            "message": {"message_id": 8, "chat": {"id": 111}},
        },
    }]

    callback_summary = runner.poll_once(offset=1, timeout=0)

    clock[0] = AT + timedelta(hours=2, minutes=1)
    timeout_summary = runner.poll_once(offset=2, timeout=0)

    assert callback_summary.callbacks_handled == 1
    assert callback_summary.shadows_marked == 0
    assert timeout_summary.callbacks_handled == 0
    assert timeout_summary.shadows_marked == 1
    with OntologyUnitOfWork(kernel.engine) as uow:
        connection = uow.connection
        assert uow.finance.count_tickets() == 1
        assert uow.tickets.count_placements() == 1
        assert uow.finance.ledger_balance("acct-jczq") == -placed_artifact.amount
        assert uow.tickets.shadow_for_artifact(
            shadow_artifact.ticket_artifact_id
        ) is not None
        assert uow.tickets.shadow_for_artifact(
            placed_artifact.ticket_artifact_id
        ) is None
        assert connection.execute(
            select(func.count()).select_from(sf.cash_transactions)
        ).scalar_one() == 1
        assert connection.execute(
            select(func.count()).select_from(st.ticket_shadow_records)
        ).scalar_one() == 1
        action_roles = connection.execute(
            select(schema.actions.c.action_type, schema.actions.c.actor_role).where(
                schema.actions.c.action_type.in_((
                    "confirm_ticket_placement",
                    "mark_ticket_shadow",
                ))
            )
        ).all()
        permissions = connection.execute(
            select(
                schema.action_permissions.c.action_type,
                schema.action_permissions.c.actor_role,
            ).where(
                schema.action_permissions.c.action_type.in_((
                    "confirm_ticket_placement",
                    "mark_ticket_shadow",
                ))
            )
        ).all()
    assert set(action_roles) == {
        ("confirm_ticket_placement", "judge_operator"),
        ("mark_ticket_shadow", "deterministic_system"),
    }
    assert set(permissions) == {
        ("confirm_ticket_placement", "judge_operator"),
        ("mark_ticket_shadow", "deterministic_system"),
    }
