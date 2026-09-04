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
from nutmeg.ontology.finance.models import TicketStatus, TransactionKind, mint_finance_id
from nutmeg.ontology.operator.confirmation import (
    ArtifactTerminalKind,
    ArtifactTerminalReason,
    consume_artifact_terminal,
    materialize_ticket_note_drafts,
)
from nutmeg.ontology.operator.models import (
    ArtifactWorkItemLinkRow,
    ConfirmationChallengeHeadRow,
    ConfirmationChallengeRevisionRow,
    ProtectedArtifactBindingRow,
    ProtectedArtifactOfferRevisionLinkRow,
)
from nutmeg.ontology.repository.artifacts import ArtifactRetrievalRow
from nutmeg.ontology.repository.finance import CashTransactionRow, TicketRow
from nutmeg.ontology.repository.operator_result import (
    PlacementCashLinkRow,
    TelegramCallbackAttestationRow,
    TicketNoteLegRow,
    TicketNoteRow,
)
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

_OPERATOR_AUDIT_KINDS = (
    "legs",
    "prescription_difference",
    "budget",
    "deployment",
)


@dataclass(frozen=True, slots=True)
class CurrentOperatorCandidateAuditFinding:
    candidate_audit_finding_id: str
    audit_kind: str
    finding_code: str
    severity: str
    message: str
    official_match_no: str | None = None
    rule_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "candidate_audit_finding_id",
            "audit_kind",
            "finding_code",
            "severity",
            "message",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if self.audit_kind not in _OPERATOR_AUDIT_KINDS:
            raise ValueError("operator candidate audit kind is invalid")
        if self.severity not in {"WARN", "ERROR"}:
            raise ValueError("operator candidate audit severity is invalid")


@dataclass(frozen=True, slots=True)
class CurrentOperatorCandidateAudit:
    policy_version: str
    completed_audit_kinds: tuple[str, ...]
    findings: tuple[CurrentOperatorCandidateAuditFinding, ...]

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("operator candidate audit policy version is required")
        if self.completed_audit_kinds != _OPERATOR_AUDIT_KINDS:
            raise ValueError("all current operator candidate audits must be completed")
        finding_ids = tuple(
            finding.candidate_audit_finding_id for finding in self.findings
        )
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("current operator candidate audit finding IDs must be unique")


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
class CreateOperatorTicketBatchRequest:
    candidate_selection_id: str
    account_id: str
    run_date: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        for name in (
            "candidate_selection_id",
            "account_id",
            "run_date",
            "actor_id",
            "idempotency_key",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")


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
class ApproveOperatorTicketBatchRequest:
    ticket_batch_revision_id: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        for name in (
            "ticket_batch_revision_id",
            "actor_id",
            "idempotency_key",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")


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
class TelegramCallbackAttestationInput:
    account_id: str
    owner_instance_id: str
    callback_query_id: str
    sender_id: str
    chat_id: str
    message_id: str
    namespace: str
    callback_data_hash: str
    server_ingress_at: datetime
    owner_heartbeat_id: str
    bridge_received_at: datetime
    heartbeat_lease_expires_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "account_id",
            "owner_instance_id",
            "callback_query_id",
            "sender_id",
            "chat_id",
            "message_id",
            "namespace",
            "owner_heartbeat_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"Telegram attestation {name} is invalid")
        if self.account_id != "nutmeg" or self.namespace != "ntc":
            raise ValueError("Telegram attestation authority is invalid")
        if len(self.callback_data_hash) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.callback_data_hash
        ):
            raise ValueError("Telegram callback data hash is invalid")
        for name in (
            "server_ingress_at",
            "bridge_received_at",
            "heartbeat_lease_expires_at",
        ):
            _require_aware(getattr(self, name), name)
        if self.bridge_received_at < self.server_ingress_at:
            raise ValueError("Telegram bridge receipt cannot precede ingress")
        if self.heartbeat_lease_expires_at <= self.bridge_received_at:
            raise ValueError("Telegram heartbeat lease must extend past bridge receipt")

    def action_identity(self) -> dict[str, str]:
        return {
            "account_id": self.account_id,
            "owner_instance_id": self.owner_instance_id,
            "callback_query_id": self.callback_query_id,
            "sender_id": self.sender_id,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "namespace": self.namespace,
            "callback_data_hash": self.callback_data_hash,
            "server_ingress_at": self.server_ingress_at.astimezone(UTC).isoformat(),
            "owner_heartbeat_id": self.owner_heartbeat_id,
        }


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
    expected_challenge_revision: int | None = None
    telegram_attestation: TelegramCallbackAttestationInput | None = None

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        _amount_fen(self.amount)
        if (
            self.expected_challenge_revision is not None
            and self.expected_challenge_revision < 1
        ):
            raise ValueError("expected_challenge_revision must be positive")
        if (
            self.telegram_attestation is not None
            and self.telegram_attestation.server_ingress_at.astimezone(UTC)
            != self.requested_at.astimezone(UTC)
        ):
            raise ValueError("placement time must equal Telegram server ingress")


@dataclass(frozen=True, slots=True)
class MarkTicketShadowRequest:
    ticket_artifact_id: str
    confirmation_id: str | None
    reason: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        if self.reason not in {
            "confirmation_not_requested",
            "deadline_unconfirmed",
            "official_deadline_shortened",
            "official_offer_cancelled",
        }:
            raise ValueError("ticket shadow reason is invalid")


class ProtectedTicketActions:
    def __init__(
        self,
        action_service: ActionService,
        artifact_store: ContentAddressedArtifactStore,
        *,
        operator_decisions=None,
        operator_candidate_auditor=None,
    ) -> None:
        self._action_service = action_service
        self._artifact_store = artifact_store
        self._operator_decisions = operator_decisions
        self._operator_candidate_auditor = operator_candidate_auditor

    def bind_operator_candidate_auditor(self, auditor) -> None:
        """Bind the Product-owned deterministic auditor during service composition."""
        if not callable(auditor):
            raise TypeError("operator candidate auditor must be callable")
        self._operator_candidate_auditor = auditor

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

    def create_operator_ticket_batch(
        self,
        request: CreateOperatorTicketBatchRequest,
    ) -> ActionOutcome:
        """Materialize one selected v2 candidate without approving placement."""
        command = ActionCommand.create(
            action_type="create_ticket_batch",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "candidate_selection_id": request.candidate_selection_id,
                "account_id": request.account_id,
                "run_date": request.run_date,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            selected = self._operator_selection(
                uow,
                request.candidate_selection_id,
            )
            account = self._operator_account(
                uow,
                account_id=request.account_id,
                channel=selected.bundle.lane,
            )
            tickets = self._operator_candidate_tickets(uow, selected)
            current_audit = self._operator_current_audit(uow, selected)
            deadline = self._operator_offer_deadline(
                uow,
                selected,
                tickets,
                receipt_time=request.requested_at,
            )
            batch_id = f"tb-{uuid4().hex}"
            revision_ref = self._insert_operator_revision(
                uow,
                command=action,
                batch_id=batch_id,
                revision_no=1,
                supersedes_revision_id=None,
                run_date=request.run_date,
                channel=selected.bundle.lane,
                account_id=account.account_id,
                currency=account.currency,
                deadline_at=deadline,
                selected=selected,
                tickets=tickets,
                current_audit=current_audit,
                state="draft",
                requested_at=request.requested_at,
            )
            lineage_ref = self._operator_decisions.insert_ticket_decision_lineage(
                uow,
                ticket_batch_revision_id=revision_ref.object_id,
                candidate_selection_id=request.candidate_selection_id,
                action_id=action.action_id,
                created_at=request.requested_at,
            )
            return (revision_ref, lineage_ref)

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

    def approve_operator_ticket_batch(
        self,
        request: ApproveOperatorTicketBatchRequest,
    ) -> ActionOutcome:
        """Approve a v2 draft and bind every artifact to normalized lineage."""
        command = ActionCommand.create(
            action_type="approve_ticket_batch",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                "ticket_batch_revision_id": request.ticket_batch_revision_id,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            draft = uow.tickets.batch_revision(request.ticket_batch_revision_id)
            if draft is None:
                raise ValueError("operator ticket batch revision does not exist")
            current = uow.tickets.current_batch_revision(draft.ticket_batch_id)
            if (
                current is None
                or current.ticket_batch_revision_id != draft.ticket_batch_revision_id
                or draft.state != "draft"
            ):
                raise ValueError("operator ticket batch is stale or not a draft")
            lineage = uow.operator_result.ticket_decision_lineage_for_batch(
                draft.ticket_batch_revision_id
            )
            if lineage is None:
                raise ValueError("operator ticket batch has no decision lineage")
            selected = self._operator_selection(uow, lineage.candidate_selection_id)
            if (
                selected.candidate.candidate_revision_id
                != lineage.candidate_revision_id
                or selected.candidate_set.audit_policy_version
                != lineage.audit_policy_version
            ):
                raise ValueError("operator ticket candidate lineage is stale")
            current_audit = self._operator_current_audit(uow, selected)
            override_receipt_ids = self._validate_operator_audit(
                uow,
                draft,
                selected,
                current_audit,
            )
            tickets = self._operator_candidate_tickets(uow, selected)
            deadline = self._operator_offer_deadline(
                uow,
                selected,
                tickets,
                receipt_time=request.requested_at,
            )
            approved_ref = self._insert_operator_revision(
                uow,
                command=action,
                batch_id=draft.ticket_batch_id,
                revision_no=draft.revision_no + 1,
                supersedes_revision_id=draft.ticket_batch_revision_id,
                run_date=draft.run_date,
                channel=draft.channel,
                account_id=draft.account_id,
                currency=draft.currency,
                deadline_at=deadline,
                selected=selected,
                tickets=tickets,
                current_audit=current_audit,
                state="approved",
                requested_at=request.requested_at,
            )
            approved_lineage_ref = (
                self._operator_decisions.insert_ticket_decision_lineage(
                    uow,
                    ticket_batch_revision_id=approved_ref.object_id,
                    candidate_selection_id=lineage.candidate_selection_id,
                    action_id=action.action_id,
                    created_at=request.requested_at,
                )
            )
            refs: list[ObjectRef] = [approved_ref, approved_lineage_ref]
            at = request.requested_at.astimezone(UTC).isoformat()
            for ticket in tickets:
                legs = uow.operator_result.candidate_ticket_legs(
                    ticket.candidate_ticket_id
                )
                offer_ids = tuple(
                    dict.fromkeys(leg.official_offer_revision_id for leg in legs)
                )
                ticket_document = self._operator_ticket_document(ticket, legs)
                artifact_document = {
                    "schema_version": "2",
                    "lineage_revision_id": approved_lineage_ref.object_id,
                    "candidate_ticket_id": ticket.candidate_ticket_id,
                    "ticket_index": ticket.ticket_index,
                    "candidate_content_hash": selected.candidate.content_hash,
                    "audit_policy_version": selected.candidate_set.audit_policy_version,
                    "audit_finding_ids": [
                        finding.candidate_audit_finding_id
                        for finding in current_audit.findings
                    ],
                    "override_receipt_ids": list(override_receipt_ids),
                    "fixed_prize_policy_revision_id": (
                        ticket.fixed_prize_policy_revision_id
                    ),
                    "frozen_deadline_at": deadline.astimezone(UTC).isoformat(),
                    "offer_revision_ids": list(offer_ids),
                    "ticket": ticket_document,
                }
                blob = self._artifact_store.put_bytes(
                    canonical_bytes(artifact_document)
                )
                uow.artifacts.upsert_blob(
                    blob,
                    "application/vnd.nutmeg.audited-ticket+json",
                    at,
                )
                ticket_artifact_id = f"tat-{blob.content_hash[:32]}"
                uow.tickets.insert_ticket_artifact(
                    AuditedTicketArtifactRow(
                        ticket_artifact_id=ticket_artifact_id,
                        ticket_batch_revision_id=approved_ref.object_id,
                        ticket_index=ticket.ticket_index,
                        ticket_hash=blob.content_hash,
                        source_artifact_id=blob.artifact_id,
                        amount=ticket.stake_minor / 100,
                        currency=ticket.currency,
                        channel=draft.channel,
                        deadline_at=deadline.astimezone(UTC).isoformat(),
                        payload=artifact_document,
                        approved_at=at,
                        approved_by_action_id=action.action_id,
                    )
                )
                uow.tickets.insert_artifact_work_item_link(
                    ArtifactWorkItemLinkRow(
                        artifact_work_item_link_id=(
                            f"awil-{canonical_digest({'artifact': ticket_artifact_id})[:32]}"
                        ),
                        ticket_artifact_id=ticket_artifact_id,
                        task_family_id=lineage.task_family_id,
                        work_item_id=lineage.work_item_id,
                        task_snapshot_hash=lineage.task_snapshot_hash,
                        slate_revision_id=lineage.slate_revision_id,
                        action_id=action.action_id,
                        linked_at=at,
                    )
                )
                uow.tickets.insert_protected_artifact_binding(
                    ProtectedArtifactBindingRow(
                        protected_artifact_binding_id=(
                            "pab-"
                            + canonical_digest(
                                {
                                    "artifact": ticket_artifact_id,
                                    "binding": "v2",
                                }
                            )[:32]
                        ),
                        ticket_artifact_id=ticket_artifact_id,
                        lineage_revision_id=approved_lineage_ref.object_id,
                        candidate_revision_id=selected.candidate.candidate_revision_id,
                        candidate_ticket_id=ticket.candidate_ticket_id,
                        ticket_index=ticket.ticket_index,
                        ticket_kind=ticket.ticket_kind,
                        stake_minor=ticket.stake_minor,
                        currency=ticket.currency,
                        composition_hash=ticket.composition_hash,
                        fixed_prize_policy_revision_id=(
                            ticket.fixed_prize_policy_revision_id
                        ),
                        frozen_deadline_at=deadline.astimezone(UTC).isoformat(),
                        action_id=action.action_id,
                        created_at=at,
                    )
                )
                for offer_index, offer_id in enumerate(offer_ids):
                    uow.tickets.insert_protected_artifact_offer_revision_link(
                        ProtectedArtifactOfferRevisionLinkRow(
                            protected_artifact_offer_revision_link_id=(
                                "paol-"
                                + canonical_digest(
                                    {
                                        "artifact": ticket_artifact_id,
                                        "offer_index": offer_index,
                                        "offer": offer_id,
                                    }
                                )[:32]
                            ),
                            ticket_artifact_id=ticket_artifact_id,
                            offer_index=offer_index,
                            official_offer_revision_id=offer_id,
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
        legacy_expires_at = request.requested_at + timedelta(minutes=5)
        created_challenge = False
        command = ActionCommand.create(
            action_type="issue_ticket_confirmation",
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={"ticket_artifact_id": request.ticket_artifact_id},
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            nonlocal created_challenge
            artifact = uow.tickets.ticket_artifact(request.ticket_artifact_id)
            if artifact is None:
                raise ValueError(
                    f"ticket artifact {request.ticket_artifact_id} does not exist"
                )
            binding = uow.tickets.protected_artifact_binding(
                request.ticket_artifact_id
            )
            if binding is not None:
                uow.acquire_write_lock()
                terminal = uow.tickets.artifact_terminal_receipt(
                    request.ticket_artifact_id
                )
                if terminal is not None:
                    return (
                        ObjectRef(
                            "artifact_terminal_receipt",
                            terminal.artifact_terminal_receipt_id,
                        ),
                    )
                head = uow.tickets.confirmation_challenge_head(
                    request.ticket_artifact_id
                )
                if head is not None:
                    return (
                        ObjectRef(
                            "confirmation_challenge_revision",
                            head.challenge_revision_id,
                        ),
                    )
                current_offers = self._current_artifact_offers(
                    uow,
                    request.ticket_artifact_id,
                )
                if not current_offers:
                    raise ValueError("protected artifact has no current official offers")
                from nutmeg.ontology.operator.confirmation import effective_artifact_cutoff

                cutoff = effective_artifact_cutoff(binding, current_offers)
                if request.requested_at >= cutoff:
                    raise ValueError("ticket deadline has passed")
                family_id = "confirmation-family-" + canonical_digest(
                    {"ticket_artifact_id": request.ticket_artifact_id}
                )[:32]
                challenge_id = "confirmation-revision-" + uuid4().hex
                issued_at = request.requested_at.astimezone(UTC).isoformat()
                uow.tickets.insert_confirmation_challenge_revision(
                    ConfirmationChallengeRevisionRow(
                        challenge_revision_id=challenge_id,
                        challenge_family_id=family_id,
                        legacy_confirmation_id=None,
                        revision_no=1,
                        supersedes_revision_id=None,
                        ticket_artifact_id=request.ticket_artifact_id,
                        artifact_composition_hash=binding.composition_hash,
                        lineage_revision_id=binding.lineage_revision_id,
                        nonce_hash=nonce_hash,
                        issued_at=issued_at,
                        effective_cutoff_at=cutoff.isoformat(),
                        action_id=action.action_id,
                    )
                )
                uow.tickets.insert_confirmation_challenge_head(
                    ConfirmationChallengeHeadRow(
                        ticket_artifact_id=request.ticket_artifact_id,
                        challenge_revision_id=challenge_id,
                        challenge_family_id=family_id,
                        revision_no=1,
                        updated_at=issued_at,
                    )
                )
                created_challenge = True
                return (
                    ObjectRef("confirmation_challenge_revision", challenge_id),
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
                    expires_at=legacy_expires_at.astimezone(UTC).isoformat(),
                    consumed_at=None,
                    consumed_by_action_id=None,
                )
            )
            return (ObjectRef("ticket_confirmation", confirmation_id),)

        outcome = self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )
        confirmation_id = next(
            (
                ref.object_id
                for ref in outcome.result_refs
                if ref.object_type
                in {"ticket_confirmation", "confirmation_challenge_revision"}
            ),
            None,
        )
        expires_at = None
        if confirmation_id is not None:
            with self._action_service.unit_of_work() as uow:
                challenge = uow.tickets.confirmation_challenge_revision(
                    confirmation_id
                )
                if challenge is not None:
                    expires_at = challenge.effective_cutoff_at
                else:
                    legacy = uow.tickets.confirmation(confirmation_id)
                    expires_at = None if legacy is None else legacy.expires_at
        return ConfirmationIssueResult(
            outcome=outcome,
            confirmation_id=confirmation_id,
            nonce=nonce if created_challenge or (
                outcome.action_id == command.action_id
                and confirmation_id is not None
                and expires_at == legacy_expires_at.astimezone(UTC).isoformat()
            ) else None,
            expires_at=expires_at,
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
                "telegram_attestation": (
                    None
                    if request.telegram_attestation is None
                    else request.telegram_attestation.action_identity()
                ),
            },
            requested_at=request.requested_at,
        )

        def handler(uow, action) -> tuple[ObjectRef, ...]:
            artifact = uow.tickets.ticket_artifact(request.ticket_artifact_id)
            if artifact is None:
                raise ValueError(
                    f"ticket artifact {request.ticket_artifact_id} does not exist"
                )
            binding = uow.tickets.protected_artifact_binding(
                request.ticket_artifact_id
            )
            if binding is not None:
                return self._confirm_operator_artifact(
                    uow,
                    action=action,
                    request=request,
                    artifact=artifact,
                    binding=binding,
                    nonce_hash=nonce_hash,
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

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    def _confirm_operator_artifact(
        self,
        uow,
        *,
        action: ActionCommand,
        request: ConfirmTicketPlacementRequest,
        artifact: AuditedTicketArtifactRow,
        binding: ProtectedArtifactBindingRow,
        nonce_hash: str,
    ) -> tuple[ObjectRef, ...]:
        challenge = uow.tickets.confirmation_challenge_revision(
            request.confirmation_id
        )
        if (
            challenge is None
            or challenge.ticket_artifact_id != artifact.ticket_artifact_id
            or challenge.artifact_composition_hash != binding.composition_hash
            or challenge.lineage_revision_id != binding.lineage_revision_id
        ):
            raise ValueError("confirmation binding mismatch")
        if not hmac.compare_digest(challenge.nonce_hash, nonce_hash):
            raise ValueError("confirmation nonce mismatch")
        if (
            artifact.ticket_hash != request.ticket_hash
            or binding.stake_minor != _amount_fen(request.amount)
            or artifact.currency != request.currency
            or binding.currency != request.currency
            or artifact.channel != request.channel
        ):
            raise ValueError("confirmation binding mismatch")
        if request.placement_mode not in {"manual", "connector"}:
            raise ValueError("placement mode is invalid")
        if not request.external_reference.strip():
            raise ValueError(f"{request.placement_mode} external_reference is required")
        if not request.receipt_content or not request.receipt_content_type.strip():
            raise ValueError(f"{request.placement_mode} receipt is required")
        attestation = request.telegram_attestation
        if attestation is None:
            raise ValueError(
                "protected operator placement requires an attested OpenClaw callback"
            )
        heartbeat = uow.operator_result.telegram_owner_heartbeat(
            account_id=attestation.account_id,
            owner_instance_id=attestation.owner_instance_id,
        )
        if (
            heartbeat is None
            or heartbeat.telegram_owner_heartbeat_id
            != attestation.owner_heartbeat_id
        ):
            raise ValueError("Telegram owner heartbeat attestation is unavailable")
        other_fresh = tuple(
            row
            for row in uow.operator_result.telegram_owner_heartbeats(
                account_id=attestation.account_id
            )
            if row.owner_instance_id != attestation.owner_instance_id
            and datetime.fromisoformat(row.observed_at)
            <= attestation.bridge_received_at.astimezone(UTC) + timedelta(seconds=2)
            and datetime.fromisoformat(row.lease_expires_at)
            > attestation.bridge_received_at.astimezone(UTC)
        )
        if other_fresh:
            raise ValueError("telegram_update_owner_conflict")
        current_observed = datetime.fromisoformat(heartbeat.observed_at)
        if attestation.bridge_received_at.astimezone(UTC) > current_observed:
            renewed = uow.operator_result.renew_telegram_owner_heartbeat(
                heartbeat_id=heartbeat.telegram_owner_heartbeat_id,
                expected_sequence=heartbeat.heartbeat_sequence,
                heartbeat_sequence=heartbeat.heartbeat_sequence + 1,
                observed_at=(
                    attestation.bridge_received_at.astimezone(UTC).isoformat()
                ),
                lease_expires_at=(
                    attestation.heartbeat_lease_expires_at.astimezone(UTC).isoformat()
                ),
            )
            if not renewed:
                raise ValueError("Telegram owner heartbeat sequence changed")

        transition = consume_artifact_terminal(
            uow,
            ticket_artifact_id=artifact.ticket_artifact_id,
            challenge_revision_id=challenge.challenge_revision_id,
            expected_challenge_revision=(
                request.expected_challenge_revision or challenge.revision_no
            ),
            terminal_kind=ArtifactTerminalKind.PLACED,
            terminal_reason=ArtifactTerminalReason.ACTUAL_PLACEMENT_CONFIRMED,
            action_id=action.action_id,
            ingress_at=request.requested_at,
        )
        terminal_ref = ObjectRef(
            "artifact_terminal_receipt",
            transition.receipt.artifact_terminal_receipt_id,
        )
        if not transition.created or not transition.requested_transition_won:
            return (terminal_ref,)

        candidate = next(
            (
                row
                for row in uow.operator_result.candidate_tickets(
                    binding.candidate_revision_id
                )
                if row.candidate_ticket_id == binding.candidate_ticket_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError("protected artifact candidate ticket is missing")
        candidate_legs = uow.operator_result.candidate_ticket_legs(
            binding.candidate_ticket_id
        )
        if (
            candidate.candidate_ticket_id != binding.candidate_ticket_id
            or candidate.ticket_index != binding.ticket_index
            or candidate.ticket_kind != binding.ticket_kind
            or candidate.stake_minor != binding.stake_minor
            or candidate.currency != binding.currency
            or candidate.composition_hash != binding.composition_hash
            or candidate.fixed_prize_policy_revision_id
            != binding.fixed_prize_policy_revision_id
        ):
            raise ValueError("protected artifact candidate binding has drifted")
        notes = materialize_ticket_note_drafts(candidate, candidate_legs)
        if sum(note.stake_minor for note in notes) != binding.stake_minor:
            raise ValueError("ticket note stake does not reconcile to artifact")
        batch = uow.tickets.batch_revision(artifact.ticket_batch_revision_id)
        if batch is None or batch.account_id.strip() == "":
            raise ValueError("protected artifact cash account is missing")

        at = request.requested_at.astimezone(UTC).isoformat()
        ticket_id = mint_finance_id("tk")
        uow.finance.insert_ticket(
            TicketRow(
                ticket_id=ticket_id,
                channel=artifact.channel,
                proposal_id=None,
                approved_at=at,
                status=TicketStatus.APPROVED.value,
                structure=candidate.structure_code,
                total_stake=binding.stake_minor / 100,
                currency=binding.currency,
                account_id=batch.account_id,
                ticket_kind=binding.ticket_kind,
                stake_minor=binding.stake_minor,
                fixed_prize_policy_revision_id=(
                    binding.fixed_prize_policy_revision_id
                ),
            )
        )
        refs: list[ObjectRef] = [terminal_ref, ObjectRef("ticket", ticket_id)]
        for note_index, note in enumerate(notes):
            note_id = "tn-" + canonical_digest(
                {
                    "action_id": action.action_id,
                    "ticket_id": ticket_id,
                    "note_index": note_index,
                    "composition_hash": note.composition_hash,
                }
            )[:32]
            uow.operator_result.insert_ticket_note(
                TicketNoteRow(
                    ticket_note_id=note_id,
                    ticket_id=ticket_id,
                    ticket_artifact_id=artifact.ticket_artifact_id,
                    note_index=note_index,
                    ticket_kind=note.ticket_kind,
                    structure_code=note.structure_code,
                    group_code=note.group_code,
                    currency=note.currency,
                    unit_stake_minor=note.unit_stake_minor,
                    unit_count=note.unit_count,
                    stake_minor=note.stake_minor,
                    composition_hash=note.composition_hash,
                    fixed_prize_policy_revision_id=(
                        note.fixed_prize_policy_revision_id
                    ),
                    action_id=action.action_id,
                    created_at=at,
                )
            )
            refs.append(ObjectRef("ticket_note", note_id))
            for leg_index, leg in enumerate(note.legs):
                leg_id = "tnl-" + canonical_digest(
                    {
                        "ticket_note_id": note_id,
                        "leg_index": leg_index,
                        "offer": leg.official_offer_revision_id,
                        "market": leg.market_definition_id,
                        "selection": leg.selection_code,
                    }
                )[:32]
                uow.operator_result.insert_ticket_note_leg(
                    TicketNoteLegRow(
                        ticket_note_leg_id=leg_id,
                        ticket_note_id=note_id,
                        leg_index=leg_index,
                        official_offer_revision_id=(
                            leg.official_offer_revision_id
                        ),
                        match_id=leg.match_id,
                        market_definition_id=leg.market_definition_id,
                        selection_code=leg.selection_code,
                        quote_id=leg.quote_id,
                        booked_decimal_odds=leg.booked_decimal_odds,
                        settlement_parameter_decimal=(
                            leg.settlement_parameter_decimal
                        ),
                        fixed_prize_policy_revision_id=(
                            leg.fixed_prize_policy_revision_id
                        ),
                        action_id=action.action_id,
                    )
                )
                refs.append(ObjectRef("ticket_note_leg", leg_id))

        receipt = self._artifact_store.put_bytes(request.receipt_content)
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
                ticket_id=ticket_id,
                placement_mode=request.placement_mode,
                external_reference=request.external_reference,
                receipt_artifact_id=receipt.artifact_id,
                receipt_retrieval_id=retrieval_id,
                placed_at=at,
                action_id=action.action_id,
            )
        )
        callback_attestation_id = "tca-" + canonical_digest(
            attestation.action_identity()
        )[:32]
        uow.operator_result.insert_telegram_callback_attestation(
            TelegramCallbackAttestationRow(
                telegram_callback_attestation_id=callback_attestation_id,
                account_id=attestation.account_id,
                owner_instance_id=attestation.owner_instance_id,
                callback_query_id=attestation.callback_query_id,
                sender_id=attestation.sender_id,
                chat_id=attestation.chat_id,
                message_id=attestation.message_id,
                namespace=attestation.namespace,
                callback_data_hash=attestation.callback_data_hash,
                server_ingress_at=(
                    attestation.server_ingress_at.astimezone(UTC).isoformat()
                ),
                owner_heartbeat_id=attestation.owner_heartbeat_id,
                source_artifact_id=receipt.artifact_id,
                source_artifact_retrieval_id=retrieval_id,
                action_id=action.action_id,
                created_at=at,
            )
        )
        transaction_id = mint_finance_id("cx")
        uow.finance.insert_cash_transaction(
            CashTransactionRow(
                transaction_id=transaction_id,
                account_id=batch.account_id,
                ticket_id=ticket_id,
                ticket_settlement_id=None,
                kind=TransactionKind.STAKE.value,
                amount=-(binding.stake_minor / 100),
                occurred_at=at,
                idempotency_key=f"{action.action_id}:stake",
                amount_minor=-binding.stake_minor,
                currency=binding.currency,
            )
        )
        cash_link_id = "pcl-" + canonical_digest(
            {
                "ticket_id": ticket_id,
                "transaction_id": transaction_id,
                "stake_minor": binding.stake_minor,
                "currency": binding.currency,
            }
        )[:32]
        uow.operator_result.insert_placement_cash_link(
            PlacementCashLinkRow(
                placement_cash_link_id=cash_link_id,
                ticket_id=ticket_id,
                transaction_id=transaction_id,
                stake_minor=binding.stake_minor,
                currency=binding.currency,
                action_id=action.action_id,
                created_at=at,
            )
        )
        persisted_terminal = uow.tickets.artifact_terminal_receipt(
            artifact.ticket_artifact_id
        )
        persisted_placement = uow.tickets.placement_for_artifact(
            artifact.ticket_artifact_id
        )
        persisted_notes = uow.operator_result.ticket_notes(ticket_id)
        persisted_note_ids = {row.ticket_note_id for row in persisted_notes}
        persisted_leg_ids = {
            row.ticket_note_leg_id
            for note in persisted_notes
            for row in uow.operator_result.ticket_note_legs(note.ticket_note_id)
        }
        expected_note_ids = {
            ref.object_id for ref in refs if ref.object_type == "ticket_note"
        }
        expected_leg_ids = {
            ref.object_id for ref in refs if ref.object_type == "ticket_note_leg"
        }
        persisted_attestation = (
            uow.operator_result.telegram_callback_attestation(
                account_id=attestation.account_id,
                callback_query_id=attestation.callback_query_id,
            )
        )
        persisted_cash_link = uow.operator_result.placement_cash_link(ticket_id)
        if (
            persisted_terminal is None
            or persisted_terminal.artifact_terminal_receipt_id
            != transition.receipt.artifact_terminal_receipt_id
            or persisted_placement is None
            or persisted_placement.ticket_placement_id != placement_id
            or persisted_note_ids != expected_note_ids
            or persisted_leg_ids != expected_leg_ids
            or persisted_attestation is None
            or persisted_attestation.telegram_callback_attestation_id
            != callback_attestation_id
            or persisted_cash_link is None
            or persisted_cash_link.placement_cash_link_id != cash_link_id
            or persisted_cash_link.transaction_id != transaction_id
        ):
            raise RuntimeError("placement materialization did not reconcile")
        refs.extend(
            (
                ObjectRef("ticket_placement", placement_id),
                ObjectRef("source_artifact", receipt.artifact_id),
                ObjectRef("artifact_retrieval", retrieval_id),
                ObjectRef("cash_transaction", transaction_id),
                ObjectRef("placement_cash_link", cash_link_id),
                ObjectRef(
                    "telegram_callback_attestation",
                    callback_attestation_id,
                ),
            )
        )
        return tuple(refs)

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
            binding = uow.tickets.protected_artifact_binding(
                request.ticket_artifact_id
            )
            if binding is not None:
                transition = consume_artifact_terminal(
                    uow,
                    ticket_artifact_id=request.ticket_artifact_id,
                    challenge_revision_id=request.confirmation_id,
                    terminal_kind=ArtifactTerminalKind.SHADOW,
                    terminal_reason=ArtifactTerminalReason(request.reason),
                    action_id=action.action_id,
                    ingress_at=request.requested_at,
                )
                terminal_ref = ObjectRef(
                    "artifact_terminal_receipt",
                    transition.receipt.artifact_terminal_receipt_id,
                )
                if not transition.created:
                    return (terminal_ref,)
                work_link = uow.tickets.artifact_work_item_link(
                    request.ticket_artifact_id
                )
                if work_link is None or self._operator_decisions is None:
                    raise ValueError(
                        "protected artifact review eligibility is not configured"
                    )
                fact = self._operator_decisions.insert_artifact_terminal_review_eligibility(
                    uow,
                    action_id=action.action_id,
                    fact_index=0,
                    work_link=work_link,
                    artifact_terminal_receipt=transition.receipt,
                    created_at=request.requested_at,
                )
                return (
                    terminal_ref,
                    ObjectRef(
                        "operator_review_eligibility_fact",
                        fact.review_eligibility_fact_id,
                    ),
                )
            if request.confirmation_id is None:
                raise ValueError("legacy ticket shadow requires a confirmation")
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

        return self._action_service.execute(
            command,
            handler,
            acquire_write_lock=True,
        )

    def _operator_selection(self, uow, candidate_selection_id: str):
        if self._operator_decisions is None:
            raise ValueError("operator decision lineage is not configured")
        return self._operator_decisions.resolve_current_selection_in_uow(
            uow,
            candidate_selection_id=candidate_selection_id,
        )

    def _operator_current_audit(self, uow, selected) -> CurrentOperatorCandidateAudit:
        if self._operator_candidate_auditor is None:
            raise ValueError("current operator candidate audit is not configured")
        result = self._operator_candidate_auditor(uow, selected)
        if not isinstance(result, CurrentOperatorCandidateAudit):
            raise TypeError("operator candidate auditor returned an invalid result")
        if result.policy_version != selected.candidate_set.audit_policy_version:
            raise ValueError("operator candidate audit policy is stale; regenerate candidates")
        return result

    @staticmethod
    def _operator_account(uow, *, account_id: str, channel: str):
        account = uow.finance.account(account_id)
        if account is None or account.status != "active":
            raise ValueError(f"active cash account {account_id} is required")
        if account.channel_scope not in {channel, "all"}:
            raise ValueError("ticket channel is outside cash account scope")
        return account

    @staticmethod
    def _operator_candidate_tickets(uow, selected):
        candidate = selected.candidate
        if candidate.partition == "over_cap":
            raise ValueError("over-cap candidate cannot materialize")
        if candidate.partition not in {"eligible", "audit_blocked"}:
            raise ValueError("candidate partition cannot materialize")
        tickets = uow.operator_result.candidate_tickets(
            candidate.candidate_revision_id
        )
        metric = uow.operator_result.candidate_metric(candidate.candidate_revision_id)
        if metric is None or not tickets:
            raise ValueError("selected candidate composition is incomplete")
        if (
            metric.ticket_count != len(tickets)
            or metric.stake_minor != sum(ticket.stake_minor for ticket in tickets)
            or any(ticket.currency != metric.currency for ticket in tickets)
        ):
            raise ValueError("candidate ticket count, stake, or currency does not reconcile")
        for ticket in tickets:
            legs = uow.operator_result.candidate_ticket_legs(ticket.candidate_ticket_id)
            if not legs:
                raise ValueError("candidate ticket has no normalized legs")
        return tickets

    @staticmethod
    def _operator_offer_deadline(
        uow,
        selected,
        tickets,
        *,
        receipt_time: datetime,
    ) -> datetime:
        current_slate = uow.operator_sale.current_slate(
            selected.bundle.lane,
            selected.bundle.business_key,
        )
        if (
            current_slate is None
            or current_slate.slate_revision_id
            != selected.candidate_set.slate_revision_id
        ):
            raise ValueError("candidate slate is stale or superseded")
        offers = {
            row.official_offer_revision_id: row
            for row in uow.operator_sale.offer_revisions_for_slate(
                current_slate.slate_revision_id
            )
        }
        offer_ids = {
            leg.official_offer_revision_id
            for ticket in tickets
            for leg in uow.operator_result.candidate_ticket_legs(
                ticket.candidate_ticket_id
            )
        }
        if not offer_ids or not offer_ids <= set(offers):
            raise ValueError("candidate has no complete official offer scope")
        received_at = receipt_time.astimezone(UTC)
        deadlines: list[datetime] = []
        for offer_id in sorted(offer_ids):
            offer = offers[offer_id]
            current_offer = uow.operator_sale.current_offer_by_family(
                offer.official_offer_family_id
            )
            opens_at = _parse_aware(offer.sale_opens_at, "sale_opens_at")
            deadline_at = _parse_aware(offer.sale_deadline_at, "sale_deadline_at")
            if (
                current_offer is None
                or current_offer.official_offer_revision_id != offer_id
                or offer.status != "on_sale"
                or received_at < opens_at
                or received_at >= deadline_at
            ):
                raise ValueError("official offer is closed, stale, or at its deadline")
            deadlines.append(deadline_at)
        return min(deadlines)

    @staticmethod
    def _current_artifact_offers(uow, ticket_artifact_id: str) -> tuple[object, ...]:
        offers = []
        for link in uow.tickets.protected_artifact_offer_revision_links(
            ticket_artifact_id
        ):
            source = uow.operator_sale.offer_revision(
                link.official_offer_revision_id
            )
            if source is None:
                raise ValueError("protected artifact offer revision is missing")
            current = uow.operator_sale.current_offer_by_family(
                source.official_offer_family_id
            )
            if current is None:
                raise ValueError("protected artifact offer family has no current revision")
            offers.append(current)
        return tuple(offers)

    @staticmethod
    def _operator_ticket_document(ticket, legs) -> dict[str, object]:
        return {
            "ticket_kind": ticket.ticket_kind,
            "structure_code": ticket.structure_code,
            "group_code": ticket.group_code,
            "currency": ticket.currency,
            "unit_stake_minor": ticket.unit_stake_minor,
            "unit_count": ticket.unit_count,
            "stake_minor": ticket.stake_minor,
            "composition_hash": ticket.composition_hash,
            "fixed_prize_policy_revision_id": ticket.fixed_prize_policy_revision_id,
            "legs": [
                {
                    "official_offer_revision_id": leg.official_offer_revision_id,
                    "match_id": leg.match_id,
                    "market_definition_id": leg.market_definition_id,
                    "selection_code": leg.selection_code,
                    "quote_id": leg.quote_id,
                    "booked_decimal_odds": leg.booked_decimal_odds,
                    "settlement_parameter_decimal": (
                        leg.settlement_parameter_decimal
                    ),
                }
                for leg in legs
            ],
        }

    def _insert_operator_revision(
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
        selected,
        tickets,
        current_audit: CurrentOperatorCandidateAudit,
        state: str,
        requested_at: datetime,
    ) -> ObjectRef:
        if any(ticket.currency != currency for ticket in tickets):
            raise ValueError("candidate currency does not match cash account")
        ticket_documents = [
            self._operator_ticket_document(
                ticket,
                uow.operator_result.candidate_ticket_legs(ticket.candidate_ticket_id),
            )
            for ticket in tickets
        ]
        audit_documents = [
            {
                "level": finding.severity,
                "code": finding.finding_code,
                "match_no": finding.official_match_no,
                "message": finding.message,
                "rule_id": finding.rule_id,
                "candidate_audit_finding_id": (
                    finding.candidate_audit_finding_id
                ),
            }
            for finding in current_audit.findings
        ]
        revision_id = f"tbr-{uuid4().hex}"
        document = {
            "schema_version": "2",
            "ticket_batch_id": batch_id,
            "ticket_batch_revision_id": revision_id,
            "revision_no": revision_no,
            "supersedes_revision_id": supersedes_revision_id,
            "run_date": run_date,
            "channel": channel,
            "account_id": account_id,
            "currency": currency,
            "deadline_at": deadline_at.astimezone(UTC).isoformat(),
            "candidate_selection_id": selected.selection.candidate_selection_id,
            "candidate_revision_id": selected.candidate.candidate_revision_id,
            "tickets": ticket_documents,
            "audit_findings": audit_documents,
            "state": state,
        }
        blob = self._artifact_store.put_bytes(canonical_bytes(document))
        at = requested_at.astimezone(UTC).isoformat()
        uow.artifacts.upsert_blob(
            blob,
            "application/vnd.nutmeg.ticket-batch+json",
            at,
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
                input_legs=[
                    leg
                    for ticket in ticket_documents
                    for leg in ticket["legs"]
                ],
                composition={
                    "schema_version": "2",
                    "tickets": ticket_documents,
                    "ticket_count": len(ticket_documents),
                    "stake_minor": sum(ticket.stake_minor for ticket in tickets),
                },
                audit_findings=audit_documents,
                state=state,
                content_hash=blob.content_hash,
                source_artifact_id=blob.artifact_id,
                created_at=at,
                created_by_action_id=command.action_id,
            )
        )
        return ObjectRef("ticket_batch_revision", revision_id)

    @staticmethod
    def _validate_operator_audit(
        uow,
        draft,
        selected,
        current_audit: CurrentOperatorCandidateAudit,
    ) -> tuple[str, ...]:
        findings = current_audit.findings
        if any(
            finding.audit_kind == "prescription_difference"
            and not (finding.rule_id or "").strip()
            for finding in findings
        ):
            raise ValueError("every prescription deviation requires a registered Rule ID")
        errors = {
            finding.candidate_audit_finding_id: finding
            for finding in findings
            if finding.severity == "ERROR"
        }
        direct_links = (
            uow.operator_result.candidate_generation_override_links_for_batch(
                draft.ticket_batch_revision_id
            )
        )
        current_generation_id = selected.candidate_set.generation_request_id
        if direct_links and not any(
            link.generation_request_id == current_generation_id
            for link in direct_links
        ):
            raise ValueError("ticket audit override requires candidate regeneration")

        inherited_links = uow.operator_result.candidate_generation_override_links(
            current_generation_id
        )
        if inherited_links:
            receipts = tuple(
                uow.operator_result.ticket_audit_override_receipt(
                    link.override_receipt_id
                )
                for link in inherited_links
            )
            if any(receipt is None for receipt in receipts):
                raise ValueError("candidate regeneration override lineage is incomplete")
            matching = ProtectedTicketActions._match_inherited_operator_overrides(
                uow,
                errors=tuple(errors.values()),
                receipts=tuple(receipt for receipt in receipts if receipt is not None),
                candidate_content_hash=selected.candidate.content_hash,
                audit_policy_version=selected.candidate_set.audit_policy_version,
            )
        else:
            receipts = uow.operator_result.ticket_audit_override_receipts_for_batch(
                draft.ticket_batch_revision_id
            )
            matching = {
                receipt.candidate_audit_finding_id: receipt
                for receipt in receipts
                if receipt.candidate_revision_id
                == selected.candidate.candidate_revision_id
                and receipt.candidate_content_hash == selected.candidate.content_hash
                and receipt.audit_policy_version
                == selected.candidate_set.audit_policy_version
            }
            if set(matching) != set(errors):
                if errors:
                    raise ValueError("ticket audit ERROR requires exact current overrides")
                if matching:
                    raise ValueError(
                        "ticket audit override set does not match current ERRORs"
                    )
        for finding in findings:
            if finding.severity != "WARN":
                continue
            adjudication = uow.workflow.latest_adjudication(
                "ticket_audit_finding",
                finding.candidate_audit_finding_id,
            )
            if (
                adjudication is None
                or adjudication.decision != "accept_warning"
                or not adjudication.reason.strip()
            ):
                raise ValueError(
                    "ticket audit WARN requires an explicit current adjudication"
                )
        return tuple(
            matching[finding_id].ticket_audit_override_receipt_id
            for finding_id in sorted(matching)
        )

    @staticmethod
    def _match_inherited_operator_overrides(
        uow,
        *,
        errors,
        receipts,
        candidate_content_hash: str,
        audit_policy_version: str,
    ):
        def signature(finding):
            return (
                finding.audit_kind,
                finding.finding_code,
                finding.severity,
                finding.message,
                finding.official_match_no,
                finding.rule_id,
            )

        receipts_by_signature = {}
        for receipt in receipts:
            original = uow.operator_result.candidate_audit_finding(
                receipt.candidate_audit_finding_id
            )
            if (
                original is None
                or receipt.candidate_content_hash != candidate_content_hash
                or receipt.audit_policy_version != audit_policy_version
            ):
                raise ValueError("candidate regeneration override lineage is stale")
            key = signature(original)
            if key in receipts_by_signature:
                raise ValueError("candidate regeneration override findings are ambiguous")
            receipts_by_signature[key] = receipt

        current_by_signature = {}
        for finding in errors:
            key = signature(finding)
            if key in current_by_signature:
                raise ValueError("current ticket audit ERROR findings are ambiguous")
            current_by_signature[key] = finding
        if set(receipts_by_signature) != set(current_by_signature):
            raise ValueError("ticket audit ERROR requires exact inherited overrides")
        return {
            finding.candidate_audit_finding_id: receipts_by_signature[key]
            for key, finding in current_by_signature.items()
        }

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
