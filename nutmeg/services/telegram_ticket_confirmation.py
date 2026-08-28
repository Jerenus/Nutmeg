"""Owner-only Telegram transport for protected manual ticket placement."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from nutmeg.ontology.actions.models import ActionStatus, ActorRole, canonical_json
from nutmeg.ontology.actions.protected_ticket_actions import (
    ConfirmTicketPlacementRequest,
    IssueTicketConfirmationRequest,
    MarkTicketShadowRequest,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


@dataclass(frozen=True, slots=True, repr=False)
class PreparedConfirmation:
    ticket_artifact_id: str
    confirmation_id: str
    expires_at: str
    text: str
    reply_markup: dict[str, object]
    _callback_data: str

    @property
    def callback_data(self) -> str:
        return self._callback_data

    def to_public_dict(self) -> dict[str, object]:
        return {
            "ticket_artifact_id": self.ticket_artifact_id,
            "confirmation_id": self.confirmation_id,
            "expires_at": self.expires_at,
            "message_preview": self.text,
            "callback_bytes": len(self._callback_data.encode("ascii")),
        }


class TelegramTicketConfirmationService:
    def __init__(
        self,
        *,
        kernel,
        telegram_client,
        allowed_chat_ids: set[int],
        now_fn,
    ) -> None:
        self._kernel = kernel
        self._telegram_client = telegram_client
        self._allowed_chat_ids = set(allowed_chat_ids)
        self._now_fn = now_fn

    def request_confirmation(
        self,
        *,
        ticket_artifact_id: str,
        chat_id: int,
        dry_run: bool,
        requested_at: datetime | None = None,
    ) -> PreparedConfirmation:
        self._require_owner(chat_id)
        at = requested_at or self._now_fn()
        _require_aware(at)
        issued = self._kernel.protected_tickets.issue_ticket_confirmation(
            IssueTicketConfirmationRequest(
                ticket_artifact_id=ticket_artifact_id,
                actor_id=f"operator:telegram:{chat_id}",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=(
                    f"telegram:confirmation:issue:{ticket_artifact_id}:{uuid4().hex}"
                ),
                requested_at=at,
            )
        )
        if (
            issued.outcome.status is not ActionStatus.COMMITTED
            or issued.confirmation_id is None
            or issued.nonce is None
            or issued.expires_at is None
        ):
            raise ValueError("ticket confirmation challenge was not issued")
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            artifact = uow.tickets.ticket_artifact(ticket_artifact_id)
        if artifact is None:
            raise ValueError(f"ticket artifact {ticket_artifact_id} does not exist")
        callback_data = f"ntc:{issued.nonce}"
        if len(callback_data.encode("ascii")) > 64:
            raise ValueError("Telegram confirmation callback exceeds 64 bytes")
        text = _confirmation_text(artifact)
        reply_markup: dict[str, object] = {
            "inline_keyboard": [[{
                "text": "confirmed placed",
                "callback_data": callback_data,
            }]],
        }
        prepared = PreparedConfirmation(
            ticket_artifact_id=ticket_artifact_id,
            confirmation_id=issued.confirmation_id,
            expires_at=issued.expires_at,
            text=text,
            reply_markup=reply_markup,
            _callback_data=callback_data,
        )
        if not dry_run:
            self._telegram_client.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
            )
        return prepared

    def handle_callback(self, callback: dict[str, object]) -> str:
        callback_id = callback.get("id")
        data = callback.get("data")
        message = callback.get("message")
        chat = message.get("chat") if isinstance(message, dict) else None
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        message_id = message.get("message_id") if isinstance(message, dict) else None
        if not isinstance(callback_id, str) or not callback_id.strip():
            raise ValueError("callback query id is required")
        if not isinstance(chat_id, int):
            raise ValueError("callback chat id is required")
        self._require_owner(chat_id)
        if not isinstance(data, str) or not data.startswith("ntc:"):
            raise ValueError("callback is not a ticket confirmation")
        nonce = data.removeprefix("ntc:")
        if not nonce:
            raise ValueError("confirmation nonce is required")
        nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            challenge = uow.tickets.confirmation_by_nonce_hash(nonce_hash)
            artifact = (
                uow.tickets.ticket_artifact(challenge.ticket_artifact_id)
                if challenge is not None
                else None
            )
        if challenge is None or artifact is None:
            raise ValueError("unknown confirmation")
        at = self._now_fn()
        _require_aware(at)
        receipt = canonical_json({
            "attestation": "manual_placement_confirmed",
            "callback_query_id": callback_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "ticket_artifact_id": artifact.ticket_artifact_id,
            "confirmation_id": challenge.confirmation_id,
            "attested_at": at.astimezone(UTC).isoformat(),
        }).encode("utf-8")
        outcome = self._kernel.protected_tickets.confirm_ticket_placement(
            ConfirmTicketPlacementRequest(
                ticket_artifact_id=artifact.ticket_artifact_id,
                confirmation_id=challenge.confirmation_id,
                nonce=nonce,
                ticket_hash=artifact.ticket_hash,
                amount=artifact.amount,
                currency=artifact.currency,
                channel=artifact.channel,
                placement_mode="manual",
                external_reference=f"telegram:{callback_id}",
                receipt_content=receipt,
                receipt_content_type="application/vnd.nutmeg.telegram-attestation+json",
                actor_id=f"operator:telegram:{chat_id}",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=f"telegram:confirm:{callback_id}",
                requested_at=at,
            )
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise ValueError("ticket placement confirmation was rejected")
        return "Placement recorded."

    def expire_due(self, now: datetime | None = None) -> int:
        at = now or self._now_fn()
        _require_aware(at)
        at_text = at.astimezone(UTC).isoformat()
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            candidates = uow.tickets.due_shadow_candidates(at_text)
        marked = 0
        for artifact_id, confirmation_id in candidates:
            outcome = self._kernel.protected_tickets.mark_ticket_shadow(
                MarkTicketShadowRequest(
                    ticket_artifact_id=artifact_id,
                    confirmation_id=confirmation_id,
                    reason="deadline_unconfirmed",
                    actor_id="system:telegram-confirmation",
                    actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                    idempotency_key=f"telegram:shadow:{artifact_id}",
                    requested_at=at,
                )
            )
            if outcome.status is ActionStatus.COMMITTED:
                marked += 1
        return marked

    def _require_owner(self, chat_id: int) -> None:
        if chat_id not in self._allowed_chat_ids:
            raise ValueError(f"chat id {chat_id} is not allowlisted")


def _confirmation_text(artifact) -> str:
    ticket = artifact.payload.get("ticket")
    audit_findings = artifact.payload.get("audit_findings")
    findings = audit_findings if isinstance(audit_findings, list) else []
    errors = sum(1 for item in findings if item.get("level") == "ERROR")
    warnings = sum(1 for item in findings if item.get("level") == "WARN")
    selections = ticket.get("legs", []) if isinstance(ticket, dict) else []
    return "\n".join((
        "Nutmeg manual placement confirmation",
        f"artifact: {artifact.ticket_artifact_id}",
        f"channel: {artifact.channel}",
        f"amount: {artifact.currency} {artifact.amount:.2f}",
        f"deadline: {artifact.deadline_at}",
        f"audit: ERROR={errors} WARN={warnings}",
        f"ticket_hash: {artifact.ticket_hash}",
        f"selections: {canonical_json(selections)}",
    ))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("confirmation time must be timezone-aware")
