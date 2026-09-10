import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.services.telegram_ticket_confirmation import (
    TelegramTicketConfirmationService,
)
from tests.ontology.test_protected_ticket_actions import AT
from tests.ontology.test_ticket_confirmation import _approved


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent = []

    def send_message(self, *, chat_id, text, reply_markup=None):
        self.sent.append({
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
        })
        return {"ok": True, "result": {"message_id": 8}}


def _service(kernel, client, *, now=AT):
    return TelegramTicketConfirmationService(
        kernel=kernel,
        telegram_client=client,
        allowed_chat_ids={111},
        now_fn=lambda: now,
    )


def _callback(prepared, *, callback_id="cb-1", chat_id=111):
    return {
        "id": callback_id,
        "data": prepared.callback_data,
        "message": {"message_id": 8, "chat": {"id": chat_id}},
    }


def test_dry_request_issues_challenge_and_redacts_public_preview(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    client = FakeTelegramClient()

    prepared = _service(kernel, client).request_confirmation(
        ticket_artifact_id=artifact.ticket_artifact_id,
        chat_id=111,
        dry_run=True,
        requested_at=AT,
    )

    assert re.fullmatch(r"ntc:[A-Za-z0-9_-]+", prepared.callback_data)
    assert len(prepared.callback_data.encode("ascii")) <= 64
    assert f"{artifact.amount:.2f}" in prepared.text
    assert artifact.deadline_at in prepared.text
    assert artifact.ticket_hash not in prepared.text
    assert artifact.ticket_artifact_id not in prepared.text
    assert "sel-had-home" not in prepared.text
    assert "{" not in prepared.text
    assert "核对已在应用中批准的票面后" in prepared.text
    assert client.sent == []
    public = prepared.to_public_dict()
    assert public["callback_bytes"] == len(prepared.callback_data)
    assert prepared.callback_data not in json.dumps(public)
    assert prepared.callback_data.removeprefix("ntc:") not in repr(prepared)
    with OntologyUnitOfWork(kernel.engine) as uow:
        challenge = uow.tickets.confirmation(prepared.confirmation_id)
    assert challenge is not None


def test_live_request_sends_one_owner_inline_button(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    client = FakeTelegramClient()

    prepared = _service(kernel, client).request_confirmation(
        ticket_artifact_id=artifact.ticket_artifact_id,
        chat_id=111,
        dry_run=False,
        requested_at=AT,
    )

    assert client.sent == [{
        "chat_id": 111,
        "text": prepared.text,
        "reply_markup": prepared.reply_markup,
    }]
    assert prepared.reply_markup["inline_keyboard"][0][0]["callback_data"] == (
        prepared.callback_data
    )


def test_owner_callback_books_once_and_receipt_omits_plaintext_nonce(
    tmp_path: Path,
) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    service = _service(kernel, FakeTelegramClient(), now=AT + timedelta(minutes=1))
    prepared = service.request_confirmation(
        ticket_artifact_id=artifact.ticket_artifact_id,
        chat_id=111,
        dry_run=True,
        requested_at=AT,
    )
    token = prepared.callback_data.removeprefix("ntc:")

    answer = service.handle_callback(_callback(prepared))
    replay = service.handle_callback(_callback(prepared))

    assert answer == "Placement recorded."
    assert replay == answer
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 1
        assert uow.finance.ledger_balance("acct-jczq") == -artifact.amount
        placement = uow.tickets.placement_for_artifact(artifact.ticket_artifact_id)
        action_payload = uow.connection.execute(
            select(schema.actions.c.payload_json).where(
                schema.actions.c.action_type == "confirm_ticket_placement"
            )
        ).scalar_one()
    assert placement is not None
    digest = placement.receipt_artifact_id.removeprefix("sha256:")
    receipt = (kernel.paths.artifacts / "sha256" / digest[:2] / digest).read_bytes()
    assert token.encode() not in receipt
    assert token not in action_payload
    receipt_payload = json.loads(receipt)
    assert receipt_payload["attestation"] == "manual_placement_confirmed"
    assert receipt_payload["callback_query_id"] == "cb-1"


def test_callback_rejects_unknown_token_and_unauthorized_chat(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    service = _service(kernel, FakeTelegramClient(), now=AT + timedelta(minutes=1))
    prepared = service.request_confirmation(
        ticket_artifact_id=artifact.ticket_artifact_id,
        chat_id=111,
        dry_run=True,
        requested_at=AT,
    )

    with pytest.raises(ValueError, match="unknown confirmation"):
        service.handle_callback({
            **_callback(prepared),
            "id": "cb-unknown",
            "data": "ntc:unknown",
        })
    with pytest.raises(ValueError, match="not allowlisted"):
        service.handle_callback(_callback(prepared, callback_id="cb-denied", chat_id=999))

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.count_tickets() == 0
        assert uow.finance.ledger_balance("acct-jczq") == 0.0


def test_expire_due_marks_one_shadow_and_is_idempotent(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    service = _service(
        kernel,
        FakeTelegramClient(),
        now=AT + timedelta(hours=2, minutes=1),
    )
    service.request_confirmation(
        ticket_artifact_id=artifact.ticket_artifact_id,
        chat_id=111,
        dry_run=True,
        requested_at=AT,
    )

    first = service.expire_due()
    second = service.expire_due()

    assert first == 1
    assert second == 0
    with OntologyUnitOfWork(kernel.engine) as uow:
        shadow = uow.tickets.shadow_for_artifact(artifact.ticket_artifact_id)
        assert uow.finance.count_tickets() == 0
        assert uow.finance.ledger_balance("acct-jczq") == 0.0
        shadow_key = uow.connection.execute(
            select(schema.actions.c.idempotency_key).where(
                schema.actions.c.action_type == "mark_ticket_shadow"
            )
        ).scalar_one()
    assert shadow is not None
    assert shadow.reason == "deadline_unconfirmed"
    assert shadow_key == f"telegram:shadow:{artifact.ticket_artifact_id}"


def test_request_and_callback_require_owner_chat(tmp_path: Path) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    service = _service(kernel, FakeTelegramClient())

    with pytest.raises(ValueError, match="not allowlisted"):
        service.request_confirmation(
            ticket_artifact_id=artifact.ticket_artifact_id,
            chat_id=999,
            dry_run=True,
            requested_at=AT,
        )

    with OntologyUnitOfWork(kernel.engine) as uow:
        actions = uow.connection.execute(
            select(schema.actions.c.status).where(
                schema.actions.c.action_type == "issue_ticket_confirmation"
            )
        ).all()
    assert actions == []
