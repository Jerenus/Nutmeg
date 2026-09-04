"""Shared deterministic state rules for protected ticket artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, Sequence

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.operator.models import ArtifactTerminalReceiptRow


class ArtifactTerminalKind(StrEnum):
    PLACED = "placed"
    SHADOW = "shadow"


class ArtifactTerminalReason(StrEnum):
    ACTUAL_PLACEMENT_CONFIRMED = "actual_placement_confirmed"
    CONFIRMATION_NOT_REQUESTED = "confirmation_not_requested"
    DEADLINE_UNCONFIRMED = "deadline_unconfirmed"
    HUMAN_NO_TICKET = "human_no_ticket"
    OFFICIAL_DEADLINE_SHORTENED = "official_deadline_shortened"
    OFFICIAL_OFFER_CANCELLED = "official_offer_cancelled"


class NoTicketReasonCode(StrEnum):
    HUMAN_ALL_DICE = "human_all_dice"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    NO_COMPLIANT_STRUCTURE_WITHIN_CAP = "no_compliant_structure_within_cap"
    DISCIPLINE_BRAKE = "discipline_brake"
    OPERATOR_DISCRETION = "operator_discretion"


class NoTicketReasonBasis(StrEnum):
    RULE_DERIVED = "rule_derived"
    OPERATOR_JUDGMENT = "operator_judgment"


class NoTicketCommandResult(StrEnum):
    RECORDED = "recorded"
    TASK_SNAPSHOT_CHANGED = "task_snapshot_changed"
    ALREADY_CURRENT = "already_current"


@dataclass(frozen=True, slots=True)
class ArtifactTerminalTransition:
    receipt: ArtifactTerminalReceiptRow
    created: bool
    requested_transition_won: bool


class _ProtectedArtifact(Protocol):
    frozen_deadline_at: str


class _OfficialOffer(Protocol):
    sale_deadline_at: str


_DUE_REASONS = {
    ArtifactTerminalReason.CONFIRMATION_NOT_REQUESTED,
    ArtifactTerminalReason.DEADLINE_UNCONFIRMED,
    ArtifactTerminalReason.OFFICIAL_DEADLINE_SHORTENED,
}


def _parse_aware(value: datetime | str, label: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def effective_artifact_cutoff(
    artifact: _ProtectedArtifact,
    current_offers: Sequence[_OfficialOffer],
) -> datetime:
    deadlines = [_parse_aware(artifact.frozen_deadline_at, "frozen_deadline_at")]
    deadlines.extend(
        _parse_aware(offer.sale_deadline_at, "sale_deadline_at")
        for offer in current_offers
    )
    return min(deadlines)


def validate_terminal_transition(
    *,
    terminal_kind: ArtifactTerminalKind | str,
    terminal_reason: ArtifactTerminalReason | str,
    ingress_at: datetime,
    cutoff: datetime,
) -> None:
    kind = ArtifactTerminalKind(terminal_kind)
    reason = ArtifactTerminalReason(terminal_reason)
    ingress = _parse_aware(ingress_at, "ingress_at")
    effective_cutoff = _parse_aware(cutoff, "effective cutoff")

    if (kind is ArtifactTerminalKind.PLACED) != (
        reason is ArtifactTerminalReason.ACTUAL_PLACEMENT_CONFIRMED
    ):
        raise ValueError("terminal reason is incompatible with terminal kind")
    if reason in {
        ArtifactTerminalReason.ACTUAL_PLACEMENT_CONFIRMED,
        ArtifactTerminalReason.HUMAN_NO_TICKET,
    }:
        if ingress >= effective_cutoff:
            raise ValueError("terminal transition is not before the effective cutoff")
    elif reason in _DUE_REASONS and ingress < effective_cutoff:
        raise ValueError("terminal transition is before the effective cutoff")


def validate_no_ticket_reason(
    *,
    reason_code: NoTicketReasonCode | str,
    reason_basis: NoTicketReasonBasis | str,
    reason_text: str,
    rule_ids: Sequence[str],
) -> None:
    NoTicketReasonCode(reason_code)
    basis = NoTicketReasonBasis(reason_basis)
    if not isinstance(reason_text, str) or not reason_text.strip():
        raise ValueError("no-ticket reason text is required")
    if basis is NoTicketReasonBasis.RULE_DERIVED and not tuple(rule_ids):
        raise ValueError("rule-derived no-ticket requires a named Rule")
    if any(not isinstance(rule_id, str) or not rule_id.strip() for rule_id in rule_ids):
        raise ValueError("no-ticket Rule IDs must be nonblank strings")


def consume_artifact_terminal(
    uow,
    *,
    ticket_artifact_id: str,
    terminal_kind: ArtifactTerminalKind | str,
    terminal_reason: ArtifactTerminalReason | str,
    action_id: str,
    ingress_at: datetime,
    challenge_revision_id: str | None = None,
) -> ArtifactTerminalTransition:
    """Consume one protected artifact terminal under cutoff-first SQLite CAS."""
    uow.acquire_write_lock()
    existing = uow.tickets.artifact_terminal_receipt(ticket_artifact_id)
    if existing is not None:
        requested_won = (
            existing.terminal_kind == ArtifactTerminalKind(terminal_kind).value
            and existing.terminal_reason == ArtifactTerminalReason(terminal_reason).value
            and (
                challenge_revision_id is None
                or existing.challenge_revision_id == challenge_revision_id
            )
        )
        return ArtifactTerminalTransition(existing, False, requested_won)

    binding = uow.tickets.protected_artifact_binding(ticket_artifact_id)
    work_link = uow.tickets.artifact_work_item_link(ticket_artifact_id)
    if binding is None or work_link is None:
        raise ValueError("artifact is not a protected operator work-item artifact")
    linked_offers = uow.tickets.protected_artifact_offer_revision_links(
        ticket_artifact_id
    )
    if not linked_offers:
        raise ValueError("protected artifact has no official offer binding")
    source_offers = []
    current_offers = []
    for link in linked_offers:
        source = uow.operator_sale.offer_revision(link.official_offer_revision_id)
        if source is None:
            raise ValueError("protected artifact offer revision is missing")
        current = uow.operator_sale.current_offer_by_family(
            source.official_offer_family_id
        )
        if current is None:
            raise ValueError("protected artifact offer family has no current revision")
        source_offers.append(source)
        current_offers.append(current)

    head = uow.tickets.confirmation_challenge_head(ticket_artifact_id)
    if challenge_revision_id is not None:
        challenge = uow.tickets.confirmation_challenge_revision(
            challenge_revision_id
        )
        if (
            challenge is None
            or challenge.ticket_artifact_id != ticket_artifact_id
            or head is None
            or head.challenge_revision_id != challenge_revision_id
        ):
            raise ValueError("confirmation challenge is stale or belongs to another artifact")
    resolved_challenge_id = (
        challenge_revision_id
        if challenge_revision_id is not None
        else (None if head is None else head.challenge_revision_id)
    )
    cutoff = effective_artifact_cutoff(binding, current_offers)
    ingress = _parse_aware(ingress_at, "ingress_at")
    requested_kind = ArtifactTerminalKind(terminal_kind)
    requested_reason = ArtifactTerminalReason(terminal_reason)
    resolved_kind = requested_kind
    resolved_reason = requested_reason

    cancelled = any(offer.status == "cancelled" for offer in current_offers)
    closed_early = any(
        offer.status == "sale_closed" and ingress < cutoff for offer in current_offers
    )
    deadline_shortened = any(
        _parse_aware(current.sale_deadline_at, "sale_deadline_at")
        < _parse_aware(source.sale_deadline_at, "sale_deadline_at")
        for source, current in zip(source_offers, current_offers, strict=True)
    )
    if cancelled:
        resolved_kind = ArtifactTerminalKind.SHADOW
        resolved_reason = ArtifactTerminalReason.OFFICIAL_OFFER_CANCELLED
    elif closed_early or (deadline_shortened and ingress >= cutoff):
        resolved_kind = ArtifactTerminalKind.SHADOW
        resolved_reason = ArtifactTerminalReason.OFFICIAL_DEADLINE_SHORTENED
    elif ingress >= cutoff:
        resolved_kind = ArtifactTerminalKind.SHADOW
        resolved_reason = (
            ArtifactTerminalReason.CONFIRMATION_NOT_REQUESTED
            if resolved_challenge_id is None
            else ArtifactTerminalReason.DEADLINE_UNCONFIRMED
        )

    validate_terminal_transition(
        terminal_kind=resolved_kind,
        terminal_reason=resolved_reason,
        ingress_at=ingress,
        cutoff=cutoff,
    )
    receipt_id = _stable_terminal_id(ticket_artifact_id)
    receipt = ArtifactTerminalReceiptRow(
        artifact_terminal_receipt_id=receipt_id,
        ticket_artifact_id=ticket_artifact_id,
        challenge_revision_id=resolved_challenge_id,
        terminal_kind=resolved_kind.value,
        terminal_reason=resolved_reason.value,
        effective_cutoff_at=cutoff.isoformat(),
        terminal_at=ingress.isoformat(),
        action_id=action_id,
    )
    uow.tickets.insert_artifact_terminal_receipt(receipt)
    return ArtifactTerminalTransition(
        receipt=receipt,
        created=True,
        requested_transition_won=(
            resolved_kind is requested_kind and resolved_reason is requested_reason
        ),
    )


def _stable_terminal_id(ticket_artifact_id: str) -> str:
    digest = hashlib.sha256(
        canonical_json(
            {"ticket_artifact_id": ticket_artifact_id, "state": "terminal"}
        ).encode("utf-8")
    ).hexdigest()
    return f"artifact-terminal-{digest}"


__all__ = [
    "ArtifactTerminalKind",
    "ArtifactTerminalReason",
    "ArtifactTerminalTransition",
    "NoTicketCommandResult",
    "NoTicketReasonBasis",
    "NoTicketReasonCode",
    "effective_artifact_cutoff",
    "consume_artifact_terminal",
    "validate_no_ticket_reason",
    "validate_terminal_transition",
]
