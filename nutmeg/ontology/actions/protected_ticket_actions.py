"""Governed immutable ticket-batch Actions before any money is recorded."""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.ticket_actions import LegInput
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.finance.booking import assert_current_forecast, book_ticket_rows
from nutmeg.ontology.repository.artifacts import ArtifactRetrievalRow
from nutmeg.ontology.repository.tickets import (
    AuditedTicketArtifactRow,
    ConfirmationChallengeRow,
    TicketBatchRevisionRow,
    TicketPlacementRow,
    TicketShadowRow,
)
from nutmeg.ontology.tickets.composition import (
    canonical_bytes,
    canonical_digest,
    compose_batch,
)
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


@dataclass(frozen=True, slots=True)
class ApproveTicketBatchRequest:
    ticket_batch_id: str
    expected_revision_no: int
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        if self.expected_revision_no < 1:
            raise ValueError("expected_revision_no must be positive")


@dataclass(frozen=True, slots=True)
class IssueTicketConfirmationRequest:
    ticket_artifact_id: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class ConfirmationIssueResult:
    outcome: ActionOutcome
    confirmation_id: str | None
    nonce: str | None
    expires_at: str | None


@dataclass(frozen=True, slots=True)
class ConfirmTicketPlacementRequest:
    ticket_artifact_id: str
    confirmation_id: str
    nonce: str | None
    ticket_hash: str
    amount: float
    currency: str
    channel: str
    placement_mode: str
    external_reference: str
    receipt_content: bytes
    receipt_content_type: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        _amount_fen(self.amount)


@dataclass(frozen=True, slots=True)
class MarkTicketShadowRequest:
    ticket_artifact_id: str
    confirmation_id: str
    reason: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        if self.reason != "deadline_unconfirmed":
            raise ValueError("ticket shadow reason must be deadline_unconfirmed")


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

    def approve_ticket_batch(
        self, request: ApproveTicketBatchRequest
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="approve_ticket_batch",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={"ticket_batch_id": request.ticket_batch_id},
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
                raise ValueError("only a draft or empty ticket batch can be approved")
            errors = [
                finding
                for finding in current.audit_findings
                if finding.get("level") == "ERROR"
            ]
            if errors:
                raise ValueError("ticket audit ERROR cannot be overridden")
            warning_adjudications: list[str] = []
            for finding in current.audit_findings:
                if finding.get("level") != "WARN":
                    continue
                finding_id = ticket_audit_finding_id(
                    current.ticket_batch_revision_id, finding
                )
                adjudication = uow.workflow.latest_adjudication(
                    "ticket_audit_finding", finding_id
                )
                if (
                    adjudication is None
                    or adjudication.decision != "accept_warning"
                    or not adjudication.reason.strip()
                    or (
                        not adjudication.evidence_rejected
                        and adjudication.alternative.get(
                            "no_evidence_rejected_acknowledged"
                        )
                        is not True
                    )
                ):
                    raise ValueError(f"unadjudicated WARN {finding_id}")
                warning_adjudications.append(adjudication.adjudication_id)

            legs = [TicketLegDraft.from_dict(item) for item in current.input_legs]
            deadline = _parse_aware(current.deadline_at, "deadline_at")
            self._validate_batch(
                uow,
                channel=current.channel,
                account_id=current.account_id,
                currency=current.currency,
                deadline_at=deadline,
                requested_at=request.requested_at,
                legs=legs,
            )
            refs = list(
                self._insert_revision(
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
                    legs=legs,
                    requested_at=request.requested_at,
                    state_override="approved_empty" if not legs else "approved",
                )
            )
            approved_revision_id = refs[0].object_id
            approved = uow.tickets.batch_revision(approved_revision_id)
            if approved is None:
                raise RuntimeError("approved ticket batch revision was not persisted")
            for index, ticket in enumerate(approved.composition["tickets"]):
                document = {
                    "schema_version": "1",
                    "policy_version": action.policy_version,
                    "ticket_batch_revision_id": approved_revision_id,
                    "ticket_index": index,
                    "channel": current.channel,
                    "account_id": current.account_id,
                    "currency": current.currency,
                    "deadline_at": current.deadline_at,
                    "ticket": ticket,
                    "audit_findings": approved.audit_findings,
                    "warning_adjudication_ids": warning_adjudications,
                    "approved_by_action_id": action.action_id,
                }
                blob = self._artifact_store.put_bytes(canonical_bytes(document))
                uow.artifacts.upsert_blob(
                    blob,
                    "application/vnd.nutmeg.audited-ticket+json",
                    request.requested_at.astimezone(UTC).isoformat(),
                )
                ticket_artifact_id = f"tat-{blob.content_hash[:32]}"
                uow.tickets.insert_ticket_artifact(
                    AuditedTicketArtifactRow(
                        ticket_artifact_id=ticket_artifact_id,
                        ticket_batch_revision_id=approved_revision_id,
                        ticket_index=index,
                        ticket_hash=blob.content_hash,
                        source_artifact_id=blob.artifact_id,
                        amount=float(ticket["stake_yuan"]),
                        currency=current.currency,
                        channel=current.channel,
                        deadline_at=current.deadline_at,
                        payload=document,
                        approved_at=request.requested_at.astimezone(UTC).isoformat(),
                        approved_by_action_id=action.action_id,
                    )
                )
                refs.append(ObjectRef("audited_ticket_artifact", ticket_artifact_id))
            return tuple(refs)

        return self._action_service.execute(command, handler)

    def issue_ticket_confirmation(
        self, request: IssueTicketConfirmationRequest
    ) -> ConfirmationIssueResult:
        nonce = secrets.token_urlsafe(32)
        nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        expires_at = request.requested_at + timedelta(minutes=5)
        command = ActionCommand.create(
            action_type="issue_ticket_confirmation",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={"ticket_artifact_id": request.ticket_artifact_id},
            requested_at=request.requested_at,
        )

        def handler(uow, _action) -> tuple[ObjectRef, ...]:
            artifact = uow.tickets.ticket_artifact(request.ticket_artifact_id)
            if artifact is None:
                raise ValueError(
                    f"ticket artifact {request.ticket_artifact_id} does not exist"
                )
            if uow.tickets.placement_for_artifact(request.ticket_artifact_id) is not None:
                raise ValueError("ticket artifact is already placed")
            if _parse_aware(artifact.deadline_at, "deadline_at") <= request.requested_at:
                raise ValueError("ticket deadline has passed")
            for leg in _artifact_legs(artifact):
                assert_current_forecast(uow, leg)
            confirmation_id = f"tc-{uuid4().hex}"
            uow.tickets.insert_confirmation(
                ConfirmationChallengeRow(
                    confirmation_id=confirmation_id,
                    ticket_artifact_id=artifact.ticket_artifact_id,
                    nonce_hash=nonce_hash,
                    ticket_hash=artifact.ticket_hash,
                    amount=artifact.amount,
                    currency=artifact.currency,
                    channel=artifact.channel,
                    issued_at=request.requested_at.astimezone(UTC).isoformat(),
                    expires_at=expires_at.astimezone(UTC).isoformat(),
                    consumed_at=None,
                    consumed_by_action_id=None,
                )
            )
            return (ObjectRef("ticket_confirmation", confirmation_id),)

        outcome = self._action_service.execute(command, handler)
        confirmation_id = next(
            (
                ref.object_id
                for ref in outcome.result_refs
                if ref.object_type == "ticket_confirmation"
            ),
            None,
        )
        first_execution = outcome.action_id == command.action_id and confirmation_id is not None
        return ConfirmationIssueResult(
            outcome=outcome,
            confirmation_id=confirmation_id,
            nonce=nonce if first_execution else None,
            expires_at=(
                expires_at.astimezone(UTC).isoformat() if first_execution else None
            ),
        )

    def confirm_ticket_placement(
        self, request: ConfirmTicketPlacementRequest
    ) -> ActionOutcome:
        nonce_hash = hashlib.sha256((request.nonce or "").encode("utf-8")).hexdigest()
        receipt_hash = hashlib.sha256(request.receipt_content).hexdigest()
        command = ActionCommand.create(
            action_type="confirm_ticket_placement",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "ticket_artifact_id": request.ticket_artifact_id,
                "confirmation_id": request.confirmation_id,
                "nonce_hash": nonce_hash,
                "ticket_hash": request.ticket_hash,
                "amount_fen": _amount_fen(request.amount),
                "currency": request.currency,
                "channel": request.channel,
                "placement_mode": request.placement_mode,
                "external_reference": request.external_reference,
                "receipt_hash": receipt_hash,
                "receipt_size": len(request.receipt_content),
                "receipt_content_type": request.receipt_content_type,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            artifact = uow.tickets.ticket_artifact(request.ticket_artifact_id)
            if artifact is None:
                raise ValueError(
                    f"ticket artifact {request.ticket_artifact_id} does not exist"
                )
            placement = uow.tickets.placement_for_artifact(request.ticket_artifact_id)
            if placement is not None:
                raise ValueError("ticket artifact is already placed")
            challenge = uow.tickets.confirmation(request.confirmation_id)
            if challenge is None or challenge.ticket_artifact_id != artifact.ticket_artifact_id:
                raise ValueError("confirmation binding mismatch")
            if challenge.consumed_at is not None:
                raise ValueError("confirmation is already consumed")
            if _parse_aware(challenge.expires_at, "expires_at") <= request.requested_at:
                raise ValueError("confirmation has expired")
            if _parse_aware(artifact.deadline_at, "deadline_at") <= request.requested_at:
                raise ValueError("ticket deadline has passed")
            if not hmac.compare_digest(challenge.nonce_hash, nonce_hash):
                raise ValueError("confirmation nonce mismatch")
            if (
                challenge.ticket_hash != request.ticket_hash
                or artifact.ticket_hash != request.ticket_hash
                or _amount_fen(challenge.amount) != _amount_fen(request.amount)
                or _amount_fen(artifact.amount) != _amount_fen(request.amount)
                or challenge.currency != request.currency
                or artifact.currency != request.currency
                or challenge.channel != request.channel
                or artifact.channel != request.channel
            ):
                raise ValueError("confirmation binding mismatch")
            if request.placement_mode not in {"manual", "connector"}:
                raise ValueError("placement mode is invalid")
            if not request.external_reference.strip():
                raise ValueError(f"{request.placement_mode} external_reference is required")
            if not request.receipt_content or not request.receipt_content_type.strip():
                raise ValueError(f"{request.placement_mode} receipt is required")

            legs = _artifact_legs(artifact)
            booking = book_ticket_rows(
                uow,
                channel=artifact.channel,
                account_id=str(artifact.payload["account_id"]),
                proposal_id=None,
                legs=legs,
                at=request.requested_at.astimezone(UTC).isoformat(),
                stake_idempotency_key=f"{action.action_id}:stake",
            )
            receipt = self._artifact_store.put_bytes(request.receipt_content)
            at = request.requested_at.astimezone(UTC).isoformat()
            uow.artifacts.upsert_blob(receipt, request.receipt_content_type, at)
            retrieval_id = "RET-" + hashlib.sha256(
                f"{action.action_id}:receipt".encode("utf-8")
            ).hexdigest()[:32]
            uow.artifacts.insert_retrieval(
                ArtifactRetrievalRow(
                    artifact_retrieval_id=retrieval_id,
                    artifact_id=receipt.artifact_id,
                    source_run_id=None,
                    source_name=f"{request.placement_mode}-ticket-receipt",
                    source_type=request.placement_mode,
                    reported_content_type=request.receipt_content_type,
                    canonical_url=None,
                    requested_url=None,
                    published_at=None,
                    retrieved_at=at,
                    status="stored",
                )
            )
            placement_id = f"tpl-{uuid4().hex}"
            uow.tickets.insert_placement(
                TicketPlacementRow(
                    ticket_placement_id=placement_id,
                    ticket_artifact_id=artifact.ticket_artifact_id,
                    ticket_id=booking.ticket_id,
                    placement_mode=request.placement_mode,
                    external_reference=request.external_reference,
                    receipt_artifact_id=receipt.artifact_id,
                    receipt_retrieval_id=retrieval_id,
                    placed_at=at,
                    action_id=action.action_id,
                )
            )
            uow.tickets.invalidate_open_confirmations(
                artifact.ticket_artifact_id, at, action.action_id
            )
            refs: list[ObjectRef] = [ObjectRef("ticket", booking.ticket_id)]
            refs.extend(ObjectRef("bet_leg", item) for item in booking.bet_leg_ids)
            if booking.transaction_id is not None:
                refs.append(ObjectRef("cash_transaction", booking.transaction_id))
            refs.extend(
                (
                    ObjectRef("ticket_placement", placement_id),
                    ObjectRef("source_artifact", receipt.artifact_id),
                    ObjectRef("artifact_retrieval", retrieval_id),
                )
            )
            return tuple(refs)

        return self._action_service.execute(command, handler)

    def mark_ticket_shadow(self, request: MarkTicketShadowRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type="mark_ticket_shadow",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "ticket_artifact_id": request.ticket_artifact_id,
                "confirmation_id": request.confirmation_id,
                "reason": request.reason,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            artifact = uow.tickets.ticket_artifact(request.ticket_artifact_id)
            if artifact is None:
                raise ValueError(
                    f"ticket artifact {request.ticket_artifact_id} does not exist"
                )
            confirmation = uow.tickets.confirmation(request.confirmation_id)
            if (
                confirmation is None
                or confirmation.ticket_artifact_id != artifact.ticket_artifact_id
            ):
                raise ValueError("confirmation binding mismatch")
            if uow.tickets.placement_for_artifact(request.ticket_artifact_id) is not None:
                raise ValueError("ticket artifact is already placed")
            deadline = _parse_aware(artifact.deadline_at, "deadline_at")
            if deadline > request.requested_at:
                raise ValueError("ticket deadline has not passed")
            existing = uow.tickets.shadow_for_artifact(request.ticket_artifact_id)
            if existing is not None:
                return (ObjectRef("ticket_shadow", existing.ticket_shadow_id),)
            shadow_id = f"tsh-{uuid4().hex}"
            uow.tickets.insert_shadow(
                TicketShadowRow(
                    ticket_shadow_id=shadow_id,
                    ticket_artifact_id=artifact.ticket_artifact_id,
                    confirmation_id=confirmation.confirmation_id,
                    reason=request.reason,
                    deadline_at=artifact.deadline_at,
                    marked_at=request.requested_at.astimezone(UTC).isoformat(),
                    action_id=action.action_id,
                )
            )
            return (ObjectRef("ticket_shadow", shadow_id),)

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
        state_override: str | None = None,
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
            "state": state_override or ("empty" if composition.is_empty else "draft"),
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
                state=state_override or ("empty" if composition.is_empty else "draft"),
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


def _amount_fen(value: float) -> int:
    try:
        amount = Decimal(str(value)) * 100
    except InvalidOperation as error:
        raise ValueError("amount must be a finite currency value") from error
    if not amount.is_finite() or amount != amount.to_integral_value() or amount <= 0:
        raise ValueError("amount must be positive and exactly representable in fen")
    return int(amount)


def _artifact_legs(artifact: AuditedTicketArtifactRow) -> list[LegInput]:
    ticket = artifact.payload.get("ticket")
    if not isinstance(ticket, dict):
        raise ValueError("ticket artifact payload is malformed")
    raw_legs = ticket.get("legs")
    if not isinstance(raw_legs, list) or not raw_legs:
        raise ValueError("ticket artifact has no legs")
    share = artifact.amount / len(raw_legs)
    legs: list[LegInput] = []
    for raw in raw_legs:
        if not isinstance(raw, dict):
            raise ValueError("ticket artifact leg is malformed")
        legs.append(
            LegInput(
                match_id=str(raw["match_id"]),
                market_definition_id=str(raw["market"]),
                selection_id=str(raw["selection_id"]),
                forecast_revision_id=str(raw["forecast_revision_id"]),
                bucket=str(ticket["bucket"]),
                stake=share,
                entry_odds=float(raw["odds"]),
                entry_quote_id=(
                    str(raw["entry_quote_id"])
                    if raw.get("entry_quote_id") is not None
                    else None
                ),
                line=str(raw["line"]) if raw.get("line") is not None else None,
            )
        )
    return legs


def ticket_audit_finding_id(
    ticket_batch_revision_id: str, finding: dict[str, object]
) -> str:
    digest = canonical_digest(
        {
            "ticket_batch_revision_id": ticket_batch_revision_id,
            "level": finding.get("level"),
            "code": finding.get("code"),
            "match_no": finding.get("match_no"),
            "message": finding.get("message"),
        }
    )
    return f"taf-{digest[:32]}"
