"""Governed immutable ticket-batch Actions before any money is recorded."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.repository.tickets import TicketBatchRevisionRow
from nutmeg.ontology.tickets.composition import canonical_bytes, compose_batch
from nutmeg.ontology.tickets.models import TicketLegDraft


@dataclass(frozen=True, slots=True)
class CreateTicketBatchRequest:
    run_date: str
    channel: str
    account_id: str
    currency: str
    deadline_at: datetime
    legs: list[TicketLegDraft]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        _require_aware(self.deadline_at, "deadline_at")


@dataclass(frozen=True, slots=True)
class RemoveTicketLegRequest:
    ticket_batch_id: str
    leg_key: str
    expected_revision_no: int
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        if self.expected_revision_no < 1:
            raise ValueError("expected_revision_no must be positive")


class ProtectedTicketActions:
    def __init__(
        self,
        action_service: ActionService,
        artifact_store: ContentAddressedArtifactStore,
    ) -> None:
        self._action_service = action_service
        self._artifact_store = artifact_store

    def create_ticket_batch(
        self, request: CreateTicketBatchRequest
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="create_ticket_batch",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "run_date": request.run_date,
                "channel": request.channel,
                "account_id": request.account_id,
                "currency": request.currency,
                "deadline_at": request.deadline_at.astimezone(UTC).isoformat(),
                "legs": [leg.to_dict() for leg in request.legs],
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            self._validate_batch(
                uow,
                channel=request.channel,
                account_id=request.account_id,
                currency=request.currency,
                deadline_at=request.deadline_at,
                requested_at=request.requested_at,
                legs=request.legs,
            )
            return self._insert_revision(
                uow,
                command=action,
                batch_id=f"tb-{uuid4().hex}",
                revision_no=1,
                supersedes_revision_id=None,
                run_date=request.run_date,
                channel=request.channel,
                account_id=request.account_id,
                currency=request.currency,
                deadline_at=request.deadline_at,
                legs=request.legs,
                requested_at=request.requested_at,
            )

        return self._action_service.execute(command, handler)

    def remove_ticket_leg(
        self, request: RemoveTicketLegRequest
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="remove_ticket_leg",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "ticket_batch_id": request.ticket_batch_id,
                "leg_key": request.leg_key,
            },
            expected_versions={
                f"ticket_batch:{request.ticket_batch_id}": request.expected_revision_no
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            current = uow.tickets.assert_current_revision(
                request.ticket_batch_id, request.expected_revision_no
            )
            if current.state not in {"draft", "empty"}:
                raise ValueError("only a draft or empty ticket batch can be revised")
            legs = [TicketLegDraft.from_dict(item) for item in current.input_legs]
            retained = [leg for leg in legs if leg.leg_key != request.leg_key]
            if len(retained) == len(legs):
                raise ValueError(f"leg {request.leg_key} not found")
            deadline = _parse_aware(current.deadline_at, "deadline_at")
            self._validate_batch(
                uow,
                channel=current.channel,
                account_id=current.account_id,
                currency=current.currency,
                deadline_at=deadline,
                requested_at=request.requested_at,
                legs=retained,
            )
            return self._insert_revision(
                uow,
                command=action,
                batch_id=current.ticket_batch_id,
                revision_no=current.revision_no + 1,
                supersedes_revision_id=current.ticket_batch_revision_id,
                run_date=current.run_date,
                channel=current.channel,
                account_id=current.account_id,
                currency=current.currency,
                deadline_at=deadline,
                legs=retained,
                requested_at=request.requested_at,
            )

        return self._action_service.execute(command, handler)

    def _insert_revision(
        self,
        uow,
        *,
        command: ActionCommand,
        batch_id: str,
        revision_no: int,
        supersedes_revision_id: str | None,
        run_date: str,
        channel: str,
        account_id: str,
        currency: str,
        deadline_at: datetime,
        legs: list[TicketLegDraft],
        requested_at: datetime,
    ) -> tuple[ObjectRef, ...]:
        revision_id = f"tbr-{uuid4().hex}"
        composition = compose_batch(legs, channel=channel, made_at=requested_at)
        document = {
            "schema_version": "1",
            "ticket_batch_id": batch_id,
            "ticket_batch_revision_id": revision_id,
            "revision_no": revision_no,
            "supersedes_revision_id": supersedes_revision_id,
            "run_date": run_date,
            "channel": channel,
            "account_id": account_id,
            "currency": currency,
            "deadline_at": deadline_at.astimezone(UTC).isoformat(),
            "input_legs": [leg.to_dict() for leg in legs],
            "composition": composition.to_dict(),
        }
        blob = self._artifact_store.put_bytes(canonical_bytes(document))
        at = requested_at.astimezone(UTC).isoformat()
        uow.artifacts.upsert_blob(
            blob, "application/vnd.nutmeg.ticket-batch+json", at
        )
        uow.tickets.insert_batch_revision(
            TicketBatchRevisionRow(
                ticket_batch_revision_id=revision_id,
                ticket_batch_id=batch_id,
                revision_no=revision_no,
                supersedes_revision_id=supersedes_revision_id,
                run_date=run_date,
                channel=channel,
                account_id=account_id,
                currency=currency,
                deadline_at=deadline_at.astimezone(UTC).isoformat(),
                input_legs=[leg.to_dict() for leg in legs],
                composition=composition.to_dict(),
                audit_findings=[finding.to_dict() for finding in composition.findings],
                state="empty" if composition.is_empty else "draft",
                content_hash=blob.content_hash,
                source_artifact_id=blob.artifact_id,
                created_at=at,
                created_by_action_id=command.action_id,
            )
        )
        return (
            ObjectRef("ticket_batch_revision", revision_id),
            ObjectRef("source_artifact", blob.artifact_id),
        )

    @staticmethod
    def _validate_batch(
        uow,
        *,
        channel: str,
        account_id: str,
        currency: str,
        deadline_at: datetime,
        requested_at: datetime,
        legs: list[TicketLegDraft],
    ) -> None:
        if deadline_at <= requested_at:
            raise ValueError("deadline_at must be after requested_at")
        account = uow.finance.account(account_id)
        if account is None or account.status != "active":
            raise ValueError(f"active cash account {account_id} is required")
        if account.currency != currency:
            raise ValueError("ticket currency does not match cash account")
        if account.channel_scope not in {channel, "all"}:
            raise ValueError("ticket channel is outside cash account scope")
        keys = [leg.leg_key for leg in legs]
        if len(set(keys)) != len(keys):
            raise ValueError("ticket leg keys must be unique")
        for leg in legs:
            series_id = uow.decision.ensure_series(
                leg.match_id, leg.market_definition_id
            )
            current = uow.decision.current_committed_revision(series_id)
            if current is None or current.forecast_revision_id != leg.forecast_revision_id:
                raise ValueError(
                    f"forecast {leg.forecast_revision_id} is not the current committed "
                    f"revision for {leg.match_id}/{leg.market_definition_id}"
                )
            if current.belief_distribution != leg.fair:
                raise ValueError("leg fair distribution must match committed Forecast")
            selection_id = uow.market.selection_id_for(
                leg.market_definition_id, leg.outcome_key, leg.line
            )
            if selection_id is None and leg.line is not None:
                selection_id = uow.market.selection_id_for(
                    leg.market_definition_id, leg.outcome_key
                )
            if selection_id != leg.selection_id:
                raise ValueError("selection does not match market outcome")
            if leg.entry_quote_id is None:
                raise ValueError("entry quote is required")
            quote = uow.market.quote(leg.entry_quote_id)
            if quote is None or (
                quote.match_id != leg.match_id
                or quote.market_definition_id != leg.market_definition_id
                or quote.selection_id != leg.selection_id
                or quote.quote_status != "active"
            ):
                raise ValueError("quote does not match ticket leg")
            if not math.isclose(quote.decimal_odds, leg.odds, abs_tol=1e-9):
                raise ValueError("quote odds do not match ticket leg")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _parse_aware(value: str, name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_aware(parsed, name)
    return parsed.astimezone(UTC)
