"""Owner-only Telegram transport for protected manual ticket placement."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping
from uuid import uuid4

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionStatus,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.actions.protected_ticket_actions import (
    ConfirmTicketPlacementRequest,
    IssueTicketConfirmationRequest,
    MarkTicketShadowRequest,
    TelegramCallbackAttestationInput,
)
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.ontology.repository.operator_result import TelegramOwnerHeartbeatRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

_MAX_CALLBACK_AGE = timedelta(seconds=10)
_MAX_CALLBACK_FUTURE_SKEW = timedelta(seconds=2)


@dataclass(frozen=True, slots=True)
class TelegramOwnerStatus:
    configured: bool
    available: bool
    blocking_code: str | None
    owner_instance_id: str
    last_heartbeat_at: str | None
    lease_expires_at: str | None


class TelegramOwnerHeartbeatService:
    """Persist one formal owner registration and a mutable heartbeat lease head."""

    def __init__(
        self,
        *,
        action_service,
        account_id: str,
        owner_instance_id: str,
        transport_label: str,
        owner_mode: str,
        router_version: str,
        lease_duration: timedelta,
    ) -> None:
        if account_id != "nutmeg":
            raise ValueError("Telegram owner account must be nutmeg")
        for name, value in (
            ("owner_instance_id", owner_instance_id),
            ("transport_label", transport_label),
            ("router_version", router_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")
        if owner_mode not in {"openclaw", "native_distinct_token"}:
            raise ValueError("Telegram owner mode is invalid")
        if lease_duration <= timedelta(0):
            raise ValueError("Telegram owner lease duration must be positive")
        self._action_service = action_service
        self.account_id = account_id
        self.owner_instance_id = owner_instance_id
        self.transport_label = transport_label
        self.owner_mode = owner_mode
        self.router_version = router_version
        self.lease_duration = lease_duration

    def pulse(self, *, observed_at: datetime) -> TelegramOwnerHeartbeatRow:
        _require_aware(observed_at)
        observed = observed_at.astimezone(UTC)
        with self._action_service.unit_of_work() as uow:
            existing = uow.operator_result.telegram_owner_heartbeat(
                account_id=self.account_id,
                owner_instance_id=self.owner_instance_id,
            )
        if existing is None:
            self._register(observed)
            with self._action_service.unit_of_work() as uow:
                created = uow.operator_result.telegram_owner_heartbeat(
                    account_id=self.account_id,
                    owner_instance_id=self.owner_instance_id,
                )
            if created is None:
                raise RuntimeError("Telegram owner registration was not persisted")
            return created

        with self._action_service.unit_of_work() as uow:
            uow.acquire_write_lock()
            current = uow.operator_result.telegram_owner_heartbeat(
                account_id=self.account_id,
                owner_instance_id=self.owner_instance_id,
            )
            if current is None:
                raise RuntimeError("Telegram owner registration disappeared")
            current_observed = datetime.fromisoformat(current.observed_at)
            if observed <= current_observed:
                raise ValueError("Telegram heartbeat time must increase")
            renewed = uow.operator_result.renew_telegram_owner_heartbeat(
                heartbeat_id=current.telegram_owner_heartbeat_id,
                expected_sequence=current.heartbeat_sequence,
                heartbeat_sequence=current.heartbeat_sequence + 1,
                observed_at=observed.isoformat(),
                lease_expires_at=(observed + self.lease_duration).isoformat(),
            )
            if not renewed:
                raise ValueError("Telegram heartbeat sequence changed")
            row = uow.operator_result.telegram_owner_heartbeat(
                account_id=self.account_id,
                owner_instance_id=self.owner_instance_id,
            )
        if row is None:
            raise RuntimeError("Telegram owner heartbeat renewal was not persisted")
        return row

    def status(self, *, as_of: datetime) -> TelegramOwnerStatus:
        _require_aware(as_of)
        now = as_of.astimezone(UTC)
        with self._action_service.unit_of_work() as uow:
            rows = uow.operator_result.telegram_owner_heartbeats(
                account_id=self.account_id
            )
        own = next(
            (row for row in rows if row.owner_instance_id == self.owner_instance_id),
            None,
        )
        fresh = [
            row
            for row in rows
            if datetime.fromisoformat(row.observed_at) <= now + timedelta(seconds=2)
            and datetime.fromisoformat(row.lease_expires_at) > now
        ]
        if own is None:
            return TelegramOwnerStatus(
                configured=True,
                available=False,
                blocking_code=(
                    "telegram_update_owner_conflict"
                    if fresh
                    else "telegram_owner_missing"
                ),
                owner_instance_id=self.owner_instance_id,
                last_heartbeat_at=None,
                lease_expires_at=None,
            )
        observed = datetime.fromisoformat(own.observed_at)
        expires = datetime.fromisoformat(own.lease_expires_at)
        if observed > now + timedelta(seconds=2):
            blocking = "telegram_owner_clock_skew"
        elif len(fresh) > 1:
            blocking = "telegram_update_owner_conflict"
        elif expires <= now:
            blocking = "telegram_owner_heartbeat_expired"
        else:
            blocking = None
        return TelegramOwnerStatus(
            configured=True,
            available=blocking is None,
            blocking_code=blocking,
            owner_instance_id=self.owner_instance_id,
            last_heartbeat_at=own.observed_at,
            lease_expires_at=own.lease_expires_at,
        )

    def attest(
        self,
        *,
        owner_instance_id: str,
        observed_at: datetime,
    ) -> TelegramOwnerHeartbeatRow:
        """Resolve the registered owner without creating a separate callback Action."""
        _require_aware(observed_at)
        if owner_instance_id != self.owner_instance_id:
            raise ValueError("Telegram owner authority mismatch")
        now = observed_at.astimezone(UTC)
        with self._action_service.unit_of_work() as uow:
            rows = uow.operator_result.telegram_owner_heartbeats(
                account_id=self.account_id
            )
        own = next(
            (row for row in rows if row.owner_instance_id == owner_instance_id),
            None,
        )
        if own is None:
            raise ValueError("telegram_owner_missing")
        conflicts = tuple(
            row
            for row in rows
            if row.owner_instance_id != owner_instance_id
            and datetime.fromisoformat(row.observed_at) <= now + timedelta(seconds=2)
            and datetime.fromisoformat(row.lease_expires_at) > now
        )
        if conflicts:
            raise ValueError("telegram_update_owner_conflict")
        return own

    def _register(self, observed_at: datetime) -> None:
        identity = {
            "account_id": self.account_id,
            "owner_instance_id": self.owner_instance_id,
            "transport_label": self.transport_label,
            "owner_mode": self.owner_mode,
            "router_version": self.router_version,
        }
        digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        command = ActionCommand.create(
            action_type="register_telegram_update_owner",
            actor_id=f"system:telegram-owner:{self.owner_instance_id}",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"telegram-owner:register:{digest}",
            requested_at=observed_at,
            payload=identity,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            current = uow.operator_result.telegram_owner_heartbeat(
                account_id=self.account_id,
                owner_instance_id=self.owner_instance_id,
            )
            if current is not None:
                return (
                    ObjectRef(
                        "telegram_owner_heartbeat",
                        current.telegram_owner_heartbeat_id,
                    ),
                )
            heartbeat_id = f"toh-{digest[:32]}"
            uow.operator_result.insert_telegram_owner_heartbeat(
                TelegramOwnerHeartbeatRow(
                    telegram_owner_heartbeat_id=heartbeat_id,
                    account_id=self.account_id,
                    owner_instance_id=self.owner_instance_id,
                    transport_label=self.transport_label,
                    owner_mode=self.owner_mode,
                    router_version=self.router_version,
                    heartbeat_sequence=1,
                    observed_at=observed_at.isoformat(),
                    lease_expires_at=(
                        observed_at + self.lease_duration
                    ).isoformat(),
                    registration_action_id=action.action_id,
                )
            )
            return (ObjectRef("telegram_owner_heartbeat", heartbeat_id),)

        outcome = self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise ValueError("Telegram owner registration was rejected")


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


@dataclass(frozen=True, slots=True)
class AttestedTelegramCallback:
    account_id: str
    owner_instance_id: str
    callback_query_id: str
    sender_id: str
    chat_id: str
    message_id: str
    namespace: str
    callback_data: str
    server_ingress_at: datetime


@dataclass(frozen=True, slots=True)
class OpenClawTelegramUpdateResult:
    message: str


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

    def handle_attested_callback(
        self,
        callback: AttestedTelegramCallback,
        heartbeat: TelegramOwnerHeartbeatRow,
        *,
        bridge_received_at: datetime,
        heartbeat_lease_duration: timedelta,
    ) -> OpenClawTelegramUpdateResult:
        """Consume one OpenClaw-owned callback through the protected placement Action."""
        _require_aware(callback.server_ingress_at)
        _require_aware(bridge_received_at)
        try:
            chat_id = int(callback.chat_id)
        except ValueError as error:
            raise ValueError("callback chat id is invalid") from error
        self._require_owner(chat_id)
        if callback.namespace != "ntc" or not callback.callback_data.startswith("ntc:"):
            raise ValueError("callback is not a ticket confirmation")
        nonce = callback.callback_data.removeprefix("ntc:")
        if not nonce:
            raise ValueError("confirmation nonce is required")
        callback_data_hash = hashlib.sha256(
            callback.callback_data.encode("ascii")
        ).hexdigest()
        identity = {
            "account_id": callback.account_id,
            "owner_instance_id": callback.owner_instance_id,
            "callback_query_id": callback.callback_query_id,
            "sender_id": callback.sender_id,
            "chat_id": callback.chat_id,
            "message_id": callback.message_id,
            "namespace": callback.namespace,
            "callback_data_hash": callback_data_hash,
            "server_ingress_at": callback.server_ingress_at.astimezone(UTC).isoformat(),
            "owner_heartbeat_id": heartbeat.telegram_owner_heartbeat_id,
        }
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            existing = uow.operator_result.telegram_callback_attestation(
                account_id=callback.account_id,
                callback_query_id=callback.callback_query_id,
            )
            if existing is not None and any(
                getattr(existing, name) != value for name, value in identity.items()
            ):
                raise IdempotencyConflictError(
                    "Telegram callback ID was reused with a different attestation"
                )
            nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
            challenge = uow.tickets.confirmation_challenge_by_nonce_hash(nonce_hash)
            artifact = (
                uow.tickets.ticket_artifact(challenge.ticket_artifact_id)
                if challenge is not None
                else None
            )
        if challenge is None or artifact is None:
            raise ValueError("unknown confirmation")
        receipt = canonical_json(
            {
                "attestation": "actual_placement_confirmed",
                "account_id": callback.account_id,
                "owner_instance_id": callback.owner_instance_id,
                "callback_query_id": callback.callback_query_id,
                "sender_id": callback.sender_id,
                "chat_id": callback.chat_id,
                "message_id": callback.message_id,
                "server_ingress_at": callback.server_ingress_at.astimezone(UTC).isoformat(),
            }
        ).encode("utf-8")
        attestation = TelegramCallbackAttestationInput(
            account_id=callback.account_id,
            owner_instance_id=callback.owner_instance_id,
            callback_query_id=callback.callback_query_id,
            sender_id=callback.sender_id,
            chat_id=callback.chat_id,
            message_id=callback.message_id,
            namespace=callback.namespace,
            callback_data_hash=callback_data_hash,
            server_ingress_at=callback.server_ingress_at,
            owner_heartbeat_id=heartbeat.telegram_owner_heartbeat_id,
            bridge_received_at=bridge_received_at,
            heartbeat_lease_expires_at=(
                bridge_received_at.astimezone(UTC) + heartbeat_lease_duration
            ),
        )
        outcome = self._kernel.protected_tickets.confirm_ticket_placement(
            ConfirmTicketPlacementRequest(
                ticket_artifact_id=artifact.ticket_artifact_id,
                confirmation_id=challenge.challenge_revision_id,
                nonce=nonce,
                ticket_hash=artifact.ticket_hash,
                amount=artifact.amount,
                currency=artifact.currency,
                channel=artifact.channel,
                placement_mode="manual",
                external_reference=f"telegram:{callback.callback_query_id}",
                receipt_content=receipt,
                receipt_content_type=(
                    "application/vnd.nutmeg.telegram-attestation+json"
                ),
                actor_id=f"operator:telegram:{callback.chat_id}",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key=(
                    f"telegram:confirm:{callback.account_id}:"
                    f"{callback.callback_query_id}"
                ),
                requested_at=callback.server_ingress_at,
                expected_challenge_revision=challenge.revision_no,
                telegram_attestation=attestation,
            )
        )
        if outcome.status is not ActionStatus.COMMITTED:
            raise ValueError("ticket placement confirmation was rejected")
        with OntologyUnitOfWork(self._kernel.engine) as uow:
            terminal = uow.tickets.artifact_terminal_receipt(
                artifact.ticket_artifact_id
            )
        if terminal is None:
            raise RuntimeError("ticket placement terminal receipt is missing")
        message = (
            "Placement recorded."
            if terminal.terminal_kind == "placed"
            else "Confirmation closed; no placement was recorded."
        )
        return OpenClawTelegramUpdateResult(message=message)

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
    audit_findings = artifact.payload.get("audit_findings")
    findings = audit_findings if isinstance(audit_findings, list) else []
    errors = sum(1 for item in findings if item.get("level") == "ERROR")
    warnings = sum(1 for item in findings if item.get("level") == "WARN")
    return "\n".join((
        "Nutmeg 出票确认",
        "请核对已在应用中批准的票面后，再确认是否已经实际出票。",
        f"渠道：{artifact.channel}",
        f"金额：{artifact.currency} {artifact.amount:.2f}",
        f"确认截止：{artifact.deadline_at}",
        f"审计：{errors} 个错误，{warnings} 个警告",
        "点击确认只登记实际出票和入账，不会自动下注。",
    ))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("confirmation time must be timezone-aware")


def ingest_openclaw_telegram_update(
    interactive_envelope: object,
    *,
    trusted_account_id: str,
    owner_instance_id: str,
    bridge_received_at: datetime,
    heartbeat_service: TelegramOwnerHeartbeatService | None = None,
    confirmation_service: TelegramTicketConfirmationService | None = None,
) -> OpenClawTelegramUpdateResult:
    """Validate process authority and atomically ingest one ntc callback."""
    _require_aware(bridge_received_at)
    callback = _normalized_openclaw_callback(interactive_envelope)
    if (
        trusted_account_id != "nutmeg"
        or callback.account_id != trusted_account_id
        or callback.owner_instance_id != owner_instance_id
    ):
        raise ValueError("Telegram callback authority mismatch")
    age = bridge_received_at.astimezone(UTC) - callback.server_ingress_at.astimezone(UTC)
    if age > _MAX_CALLBACK_AGE or age < -_MAX_CALLBACK_FUTURE_SKEW:
        raise ValueError("Telegram callback timestamp skew is outside allowed window")
    if heartbeat_service is None or confirmation_service is None:
        heartbeat_service, confirmation_service = _default_openclaw_services(
            callback,
            trusted_account_id=trusted_account_id,
            owner_instance_id=owner_instance_id,
        )
    heartbeat = heartbeat_service.attest(
        owner_instance_id=owner_instance_id,
        observed_at=bridge_received_at,
    )
    return confirmation_service.handle_attested_callback(
        callback,
        heartbeat,
        bridge_received_at=bridge_received_at,
        heartbeat_lease_duration=heartbeat_service.lease_duration,
    )


def _normalized_openclaw_callback(value: object) -> AttestedTelegramCallback:
    def field(name: str):
        if isinstance(value, Mapping):
            return value.get(name)
        return getattr(value, name, None)

    if field("authorized") is not True:
        raise ValueError("callback is not authorized")
    ingress = field("server_ingress_at")
    if not isinstance(ingress, datetime):
        raise ValueError("callback ingress time is invalid")
    fields = {
        name: field(name)
        for name in (
            "account_id",
            "owner_instance_id",
            "callback_query_id",
            "sender_id",
            "chat_id",
            "message_id",
            "namespace",
            "callback_data",
        )
    }
    if any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in fields.values()
    ):
        raise ValueError("callback identity is invalid")
    callback_data = fields["callback_data"]
    try:
        if len(callback_data.encode("ascii")) > 64:
            raise ValueError("callback data is too large")
    except UnicodeEncodeError as error:
        raise ValueError("callback data must be ASCII") from error
    return AttestedTelegramCallback(**fields, server_ingress_at=ingress)


def _default_openclaw_services(
    callback: AttestedTelegramCallback,
    *,
    trusted_account_id: str,
    owner_instance_id: str,
) -> tuple[TelegramOwnerHeartbeatService, TelegramTicketConfirmationService]:
    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.wiring import build_ontology_kernel

    settings = AppSettings(_env_file=None)
    kernel = build_ontology_kernel(settings)
    if not kernel.status().initialized:
        raise ValueError("ontology is not initialized")
    allowed_chat_ids = {
        int(item.strip())
        for item in (settings.telegram_allowed_chat_ids or "").split(",")
        if item.strip()
    }
    if int(callback.chat_id) not in allowed_chat_ids:
        raise ValueError("callback chat is not allowlisted")
    action_service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    heartbeat = TelegramOwnerHeartbeatService(
        action_service=action_service,
        account_id=trusted_account_id,
        owner_instance_id=owner_instance_id,
        transport_label="openclaw-telegram",
        owner_mode="openclaw",
        router_version="ntc-v1",
        lease_duration=timedelta(seconds=90),
    )
    confirmation = TelegramTicketConfirmationService(
        kernel=kernel,
        telegram_client=None,
        allowed_chat_ids=allowed_chat_ids,
        now_fn=lambda: datetime.now(UTC),
    )
    return heartbeat, confirmation
