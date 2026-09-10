"""Shared deterministic state rules for protected ticket artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from itertools import product
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


@dataclass(frozen=True, slots=True)
class TicketNoteLegDraft:
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    selection_code: str
    quote_id: str | None
    booked_decimal_odds: str | None
    settlement_parameter_decimal: str | None
    fixed_prize_policy_revision_id: str | None


@dataclass(frozen=True, slots=True)
class TicketNoteDraft:
    ticket_kind: str
    structure_code: str
    group_code: str | None
    currency: str
    unit_stake_minor: int
    unit_count: int
    composition_hash: str
    fixed_prize_policy_revision_id: str | None
    legs: tuple[TicketNoteLegDraft, ...]

    @property
    def stake_minor(self) -> int:
        return self.unit_stake_minor * self.unit_count


class _ProtectedArtifact(Protocol):
    frozen_deadline_at: str


class _OfficialOffer(Protocol):
    sale_deadline_at: str


class _CandidateTicket(Protocol):
    ticket_kind: str
    structure_code: str
    group_code: str | None
    currency: str
    unit_stake_minor: int
    unit_count: int
    stake_minor: int
    fixed_prize_policy_revision_id: str | None


class _CandidateLeg(Protocol):
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    selection_code: str
    quote_id: str | None
    booked_decimal_odds: str | None
    settlement_parameter_decimal: str | None


_DUE_REASONS = {
    ArtifactTerminalReason.CONFIRMATION_NOT_REQUESTED,
    ArtifactTerminalReason.DEADLINE_UNCONFIRMED,
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


def materialize_ticket_note_drafts(
    ticket: _CandidateTicket,
    flattened_legs: Sequence[_CandidateLeg | TicketNoteLegDraft],
) -> tuple[TicketNoteDraft, ...]:
    """Expand one normalized candidate ticket into unique canonical paid notes."""
    if ticket.ticket_kind not in {"jczq_pass", "sfc", "renjiu"}:
        raise ValueError("unsupported ticket kind")
    if ticket.unit_stake_minor <= 0 or ticket.unit_count <= 0:
        raise ValueError("ticket unit stake and count must be positive")
    if ticket.stake_minor != ticket.unit_stake_minor * ticket.unit_count:
        raise ValueError("ticket stake does not reconcile to unit stake and count")
    if not flattened_legs:
        raise ValueError("ticket requires at least one leg")

    grouped: dict[str, list[tuple[int, _CandidateLeg | TicketNoteLegDraft]]] = {}
    for position, leg in enumerate(flattened_legs):
        grouped.setdefault(leg.official_offer_revision_id, []).append((position, leg))
    ordered_groups = sorted(grouped.values(), key=lambda rows: rows[0][0])
    choices: list[tuple[TicketNoteLegDraft, ...]] = []
    for rows in ordered_groups:
        first = rows[0][1]
        faces: list[TicketNoteLegDraft] = []
        seen_faces: set[tuple[str, str, str | None]] = set()
        for _position, row in rows:
            if row.match_id != first.match_id:
                raise ValueError("candidate faces for one offer have inconsistent bindings")
            face_key = (
                row.market_definition_id,
                row.selection_code,
                row.settlement_parameter_decimal,
            )
            if face_key in seen_faces:
                raise ValueError("candidate offer contains a duplicate face")
            seen_faces.add(face_key)
            faces.append(_normalized_note_leg(ticket, row))
        choices.append(
            tuple(
                sorted(
                    faces,
                    key=lambda item: (
                        item.market_definition_id,
                        item.settlement_parameter_decimal or "",
                        item.selection_code,
                        item.quote_id or "",
                    ),
                )
            )
        )

    combinations = tuple(product(*choices))
    if not combinations or ticket.unit_count % len(combinations) != 0:
        raise ValueError("ticket unit count does not reconcile to canonical notes")
    note_unit_count = ticket.unit_count // len(combinations)
    notes = tuple(
        TicketNoteDraft(
            ticket_kind=ticket.ticket_kind,
            structure_code=ticket.structure_code,
            group_code=ticket.group_code,
            currency=ticket.currency,
            unit_stake_minor=ticket.unit_stake_minor,
            unit_count=note_unit_count,
            composition_hash=_note_composition_hash(
                ticket=ticket,
                legs=tuple(note_legs),
                unit_count=note_unit_count,
            ),
            fixed_prize_policy_revision_id=(
                ticket.fixed_prize_policy_revision_id
            ),
            legs=tuple(note_legs),
        )
        for note_legs in combinations
    )
    if sum(note.stake_minor for note in notes) != ticket.stake_minor:
        raise ValueError("canonical note stake does not reconcile to ticket stake")
    return notes


def _normalized_note_leg(
    ticket: _CandidateTicket,
    leg: _CandidateLeg | TicketNoteLegDraft,
) -> TicketNoteLegDraft:
    leg_policy = getattr(leg, "fixed_prize_policy_revision_id", None)
    if ticket.ticket_kind == "jczq_pass":
        if ticket.fixed_prize_policy_revision_id is not None or leg_policy is not None:
            raise ValueError("JCZQ forbids a fixed-prize policy")
        if not leg.quote_id:
            raise ValueError("JCZQ note leg requires a booked quote")
        if leg.booked_decimal_odds is None:
            raise ValueError("JCZQ note leg requires booked odds")
        _require_canonical_decimal(
            leg.booked_decimal_odds,
            label="booked odds",
            positive=True,
        )
        if leg.market_definition_id == "md-hhad":
            if leg.settlement_parameter_decimal is None:
                raise ValueError("HHAD note leg requires a settlement parameter")
            _require_canonical_decimal(
                leg.settlement_parameter_decimal,
                label="settlement parameter",
            )
        elif leg.settlement_parameter_decimal is not None:
            _require_canonical_decimal(
                leg.settlement_parameter_decimal,
                label="settlement parameter",
            )
        policy = None
    else:
        if not ticket.fixed_prize_policy_revision_id:
            raise ValueError("Zucai note requires a fixed-prize policy")
        if leg_policy not in {None, ticket.fixed_prize_policy_revision_id}:
            raise ValueError("Zucai note leg policy does not match its ticket")
        if (
            leg.quote_id is not None
            or leg.booked_decimal_odds is not None
            or leg.settlement_parameter_decimal is not None
        ):
            raise ValueError("Zucai note leg forbids quote, odds, and line fields")
        policy = ticket.fixed_prize_policy_revision_id
    return TicketNoteLegDraft(
        official_offer_revision_id=leg.official_offer_revision_id,
        match_id=leg.match_id,
        market_definition_id=leg.market_definition_id,
        selection_code=leg.selection_code,
        quote_id=leg.quote_id,
        booked_decimal_odds=leg.booked_decimal_odds,
        settlement_parameter_decimal=leg.settlement_parameter_decimal,
        fixed_prize_policy_revision_id=policy,
    )


def _require_canonical_decimal(
    value: str,
    *,
    label: str,
    positive: bool = False,
) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} must be a canonical decimal") from error
    if not parsed.is_finite() or format(parsed, ".12f") != value:
        raise ValueError(f"{label} must be a canonical decimal")
    if positive and parsed <= 0:
        raise ValueError(f"{label} must be positive")
    return parsed


def _note_composition_hash(
    *,
    ticket: _CandidateTicket,
    legs: tuple[TicketNoteLegDraft, ...],
    unit_count: int,
) -> str:
    document = {
        "ticket_kind": ticket.ticket_kind,
        "structure_code": ticket.structure_code,
        "group_code": ticket.group_code,
        "currency": ticket.currency,
        "unit_stake_minor": ticket.unit_stake_minor,
        "unit_count": unit_count,
        "fixed_prize_policy_revision_id": ticket.fixed_prize_policy_revision_id,
        "legs": [
            {
                "official_offer_revision_id": leg.official_offer_revision_id,
                "match_id": leg.match_id,
                "market_definition_id": leg.market_definition_id,
                "selection_code": leg.selection_code,
                "quote_id": leg.quote_id,
                "booked_decimal_odds": leg.booked_decimal_odds,
                "settlement_parameter_decimal": leg.settlement_parameter_decimal,
                "fixed_prize_policy_revision_id": (
                    leg.fixed_prize_policy_revision_id
                ),
            }
            for leg in legs
        ],
    }
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def consume_artifact_terminal(
    uow,
    *,
    ticket_artifact_id: str,
    terminal_kind: ArtifactTerminalKind | str,
    terminal_reason: ArtifactTerminalReason | str,
    action_id: str,
    ingress_at: datetime,
    challenge_revision_id: str | None = None,
    expected_challenge_revision: int | None = None,
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
    removed_offers = []
    for link in linked_offers:
        source = uow.operator_sale.offer_revision(link.official_offer_revision_id)
        if source is None:
            raise ValueError("protected artifact offer revision is missing")
        current = uow.operator_sale.current_offer_by_family(
            source.official_offer_family_id
        )
        source_offers.append(source)
        removed_offers.append(current is None)
        current_offers.append(source if current is None else current)

    head = uow.tickets.confirmation_challenge_head(ticket_artifact_id)
    if expected_challenge_revision is not None and (
        head is None or head.revision_no != expected_challenge_revision
    ):
        raise ValueError("confirmation challenge revision is stale")
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

    cancelled = any(removed_offers) or any(
        offer.status == "cancelled" for offer in current_offers
    )
    closed_early = any(
        offer.status == "sale_closed" and ingress < cutoff for offer in current_offers
    )
    deadline_shortened = any(
        not removed
        and _parse_aware(current.sale_deadline_at, "sale_deadline_at")
        < _parse_aware(source.sale_deadline_at, "sale_deadline_at")
        for source, current, removed in zip(
            source_offers,
            current_offers,
            removed_offers,
            strict=True,
        )
    )
    if (
        requested_reason is ArtifactTerminalReason.OFFICIAL_OFFER_CANCELLED
        and not cancelled
    ):
        raise ValueError("official cancellation terminal requires a cancelled offer")
    if (
        requested_reason is ArtifactTerminalReason.OFFICIAL_DEADLINE_SHORTENED
        and not (closed_early or deadline_shortened)
    ):
        raise ValueError("official deadline terminal requires a shortened offer")
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
    "TicketNoteDraft",
    "TicketNoteLegDraft",
    "effective_artifact_cutoff",
    "consume_artifact_terminal",
    "materialize_ticket_note_drafts",
    "validate_no_ticket_reason",
    "validate_terminal_transition",
]
