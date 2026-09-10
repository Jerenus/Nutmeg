"""Pure task-settlement grading and signed-ledger planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nutmeg.ontology.finance.settlement import (
    grade_market_leg,
    jczq_note_grade,
    jczq_note_payout_minor,
    zucai_note_grade,
    zucai_note_payout_minor,
)

_FACE_TO_OUTCOME = {"3": "home", "1": "draw", "0": "away"}
_MARKET_KIND = {
    "md-had": "had",
    "md-hhad": "hhad",
    "md-ttg": "ttg",
    "md-crs": "crs",
}
SETTLEMENT_METHOD_VERSION = "operator-task-settlement-v1"
SETTLEMENT_METHOD_REGISTRY = frozenset({SETTLEMENT_METHOD_VERSION})


@dataclass(frozen=True, slots=True)
class SettlementOutcomeInput:
    outcome_revision_id: str
    match_id: str
    result_disposition: str
    home_90: int | None
    away_90: int | None


@dataclass(frozen=True, slots=True)
class SettlementLegInput:
    ticket_note_leg_id: str
    official_offer_revision_id: str
    match_id: str
    market_definition_id: str
    selection_code: str
    booked_decimal_odds: str | None
    settlement_parameter_decimal: str | None
    fixed_prize_policy_revision_id: str | None
    crs_exact_codes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SettlementNoteInput:
    ticket_note_id: str
    ticket_kind: str
    currency: str
    unit_stake_minor: int
    unit_count: int
    stake_minor: int
    fixed_prize_policy_revision_id: str | None
    legs: tuple[SettlementLegInput, ...]


@dataclass(frozen=True, slots=True)
class SettlementTicketInput:
    ticket_id: str
    ticket_kind: str
    currency: str
    stake_minor: int
    fixed_prize_policy_revision_id: str | None
    notes: tuple[SettlementNoteInput, ...]


@dataclass(frozen=True, slots=True)
class ZucaiPrizeTierInput:
    tier_code: str
    ticket_kind: str
    required_correct_count: int
    payout_minor_per_winning_note: int


@dataclass(frozen=True, slots=True)
class SettlementLegPlan:
    ticket_note_leg_id: str
    outcome_revision_id: str
    result_disposition: str
    market_result_code: str
    leg_grade: Literal["won", "lost", "void"]


@dataclass(frozen=True, slots=True)
class SettlementNotePlan:
    ticket_note_id: str
    note_grade: Literal["won", "lost", "void"]
    unit_count: int
    winning_unit_count: int
    void_unit_count: int
    correct_leg_count: int
    void_leg_count: int
    prize_tier_code: str | None
    payout_minor: int
    legs: tuple[SettlementLegPlan, ...]


@dataclass(frozen=True, slots=True)
class TicketSettlementPlan:
    ticket_id: str
    currency: str
    stake_minor: int
    distinct_note_count: int
    paid_note_unit_count: int
    winning_note_unit_count: int
    void_note_unit_count: int
    gross_payout_minor: int
    notes: tuple[SettlementNotePlan, ...]


@dataclass(frozen=True, slots=True)
class PayoutCashEntryPlan:
    transaction_kind: Literal["payout", "payout_reversal"]
    amount_minor: int
    reverses_transaction_id: str | None


def plan_payout_cash_entries(
    *,
    prior_payout_minor: int,
    new_payout_minor: int,
    predecessor_payout_transaction_id: str | None,
) -> tuple[PayoutCashEntryPlan, ...]:
    """Return the exact signed cash rows for one direct settlement transition."""
    for value, name in (
        (prior_payout_minor, "prior_payout_minor"),
        (new_payout_minor, "new_payout_minor"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if prior_payout_minor > 0:
        if (
            not isinstance(predecessor_payout_transaction_id, str)
            or not predecessor_payout_transaction_id.strip()
        ):
            raise ValueError("positive predecessor payout requires its transaction ID")
    elif predecessor_payout_transaction_id is not None:
        raise ValueError("zero predecessor payout cannot name a payout transaction")

    entries: list[PayoutCashEntryPlan] = []
    if prior_payout_minor > 0:
        entries.append(
            PayoutCashEntryPlan(
                transaction_kind="payout_reversal",
                amount_minor=-prior_payout_minor,
                reverses_transaction_id=predecessor_payout_transaction_id,
            )
        )
    if new_payout_minor > 0:
        entries.append(
            PayoutCashEntryPlan(
                transaction_kind="payout",
                amount_minor=new_payout_minor,
                reverses_transaction_id=None,
            )
        )
    return tuple(entries)


def validate_settlement_method_version(version: str) -> None:
    if version not in SETTLEMENT_METHOD_REGISTRY:
        raise ValueError("unsupported settlement method version")


def grade_ticket_settlement(
    ticket: SettlementTicketInput,
    *,
    settlement_method_version: str,
    outcomes_by_match: dict[str, SettlementOutcomeInput],
    prize_tiers: tuple[ZucaiPrizeTierInput, ...] = (),
) -> TicketSettlementPlan:
    """Grade every immutable note and leg, returning one reconciled ticket plan."""
    validate_settlement_method_version(settlement_method_version)
    _validate_ticket(ticket)
    notes = tuple(
        _grade_note(
            ticket=ticket,
            note=note,
            outcomes_by_match=outcomes_by_match,
            prize_tiers=prize_tiers,
        )
        for note in ticket.notes
    )
    return TicketSettlementPlan(
        ticket_id=ticket.ticket_id,
        currency=ticket.currency,
        stake_minor=ticket.stake_minor,
        distinct_note_count=len(notes),
        paid_note_unit_count=sum(note.unit_count for note in notes),
        winning_note_unit_count=sum(
            note.winning_unit_count for note in notes
        ),
        void_note_unit_count=sum(note.void_unit_count for note in notes),
        gross_payout_minor=sum(note.payout_minor for note in notes),
        notes=notes,
    )


def _validate_ticket(ticket: SettlementTicketInput) -> None:
    if ticket.ticket_kind not in {"jczq_pass", "sfc", "renjiu"}:
        raise ValueError("unsupported ticket kind")
    if not ticket.ticket_id.strip() or ticket.currency != "CNY":
        raise ValueError("ticket identity or currency is invalid")
    if (
        isinstance(ticket.stake_minor, bool)
        or not isinstance(ticket.stake_minor, int)
        or ticket.stake_minor <= 0
        or not ticket.notes
    ):
        raise ValueError("ticket stake and notes are invalid")
    if sum(note.stake_minor for note in ticket.notes) != ticket.stake_minor:
        raise ValueError("ticket note stake does not reconcile to ticket stake")
    fixed = ticket.ticket_kind in {"sfc", "renjiu"}
    if fixed != bool(ticket.fixed_prize_policy_revision_id):
        raise ValueError("ticket fixed-prize policy binding is invalid")
    for note in ticket.notes:
        if (
            note.ticket_kind != ticket.ticket_kind
            or note.currency != ticket.currency
            or note.fixed_prize_policy_revision_id
            != ticket.fixed_prize_policy_revision_id
        ):
            raise ValueError("ticket note binding has drifted")
        if (
            isinstance(note.unit_stake_minor, bool)
            or not isinstance(note.unit_stake_minor, int)
            or note.unit_stake_minor <= 0
            or isinstance(note.unit_count, bool)
            or not isinstance(note.unit_count, int)
            or note.unit_count <= 0
            or note.stake_minor != note.unit_stake_minor * note.unit_count
            or not note.legs
        ):
            raise ValueError("ticket note stake does not reconcile")
        expected_legs = {"sfc": 14, "renjiu": 9}.get(ticket.ticket_kind)
        if expected_legs is not None and len(note.legs) != expected_legs:
            raise ValueError("fixed-prize note has the wrong bound leg count")
        if len({leg.official_offer_revision_id for leg in note.legs}) != len(note.legs):
            raise ValueError("ticket note repeats an official offer")


def _grade_note(
    *,
    ticket: SettlementTicketInput,
    note: SettlementNoteInput,
    outcomes_by_match: dict[str, SettlementOutcomeInput],
    prize_tiers: tuple[ZucaiPrizeTierInput, ...],
) -> SettlementNotePlan:
    legs = tuple(
        _grade_leg(
            ticket_kind=ticket.ticket_kind,
            policy_id=ticket.fixed_prize_policy_revision_id,
            leg=leg,
            outcomes_by_match=outcomes_by_match,
        )
        for leg in note.legs
    )
    correct = sum(leg.leg_grade in {"won", "void"} for leg in legs)
    void = sum(leg.leg_grade == "void" for leg in legs)
    if ticket.ticket_kind == "jczq_pass":
        note_grade = jczq_note_grade(tuple(leg.leg_grade for leg in legs))
        payout = jczq_note_payout_minor(
            stake_minor=note.stake_minor,
            leg_grades=tuple(leg.leg_grade for leg in legs),
            booked_decimal_odds=tuple(leg.booked_decimal_odds for leg in note.legs),
        )
        prize_tier_code = None
        winning_units = note.unit_count if note_grade == "won" else 0
        void_units = note.unit_count if note_grade == "void" else 0
    else:
        grade = zucai_note_grade(
            ticket_kind=ticket.ticket_kind,
            correct_leg_count=correct,
        )
        note_grade = grade.note_grade
        prize_tier_code = grade.prize_tier_code
        tier = next(
            (
                item
                for item in prize_tiers
                if item.tier_code == prize_tier_code
                and item.ticket_kind == ticket.ticket_kind
                and item.required_correct_count == correct
            ),
            None,
        )
        if prize_tier_code is not None and tier is None:
            raise ValueError("winning fixed-prize tier is not available")
        payout = zucai_note_payout_minor(
            unit_count=note.unit_count,
            payout_minor_per_winning_note=(
                0 if tier is None else tier.payout_minor_per_winning_note
            ),
            won=note_grade == "won",
        )
        winning_units = note.unit_count if note_grade == "won" else 0
        void_units = 0
    return SettlementNotePlan(
        ticket_note_id=note.ticket_note_id,
        note_grade=note_grade,
        unit_count=note.unit_count,
        winning_unit_count=winning_units,
        void_unit_count=void_units,
        correct_leg_count=correct,
        void_leg_count=void,
        prize_tier_code=prize_tier_code,
        payout_minor=payout,
        legs=legs,
    )


def _grade_leg(
    *,
    ticket_kind: str,
    policy_id: str | None,
    leg: SettlementLegInput,
    outcomes_by_match: dict[str, SettlementOutcomeInput],
) -> SettlementLegPlan:
    outcome = outcomes_by_match.get(leg.match_id)
    if outcome is None or outcome.match_id != leg.match_id:
        raise ValueError(f"Outcome is not ready for match {leg.match_id}")
    market_kind = _MARKET_KIND.get(leg.market_definition_id)
    if market_kind is None:
        raise ValueError("unsupported settlement market")
    if ticket_kind == "jczq_pass":
        if leg.fixed_prize_policy_revision_id is not None:
            raise ValueError("JCZQ leg cannot bind a fixed-prize policy")
        selection = (
            _FACE_TO_OUTCOME.get(leg.selection_code, leg.selection_code)
            if market_kind in {"had", "hhad"}
            else leg.selection_code
        )
    else:
        if (
            market_kind != "had"
            or leg.fixed_prize_policy_revision_id != policy_id
            or leg.booked_decimal_odds is not None
            or leg.settlement_parameter_decimal is not None
        ):
            raise ValueError("fixed-prize leg binding is invalid")
        selection = _FACE_TO_OUTCOME.get(leg.selection_code, "")
    grade = grade_market_leg(
        market_kind=market_kind,
        selection_code=selection,
        result_disposition=outcome.result_disposition,
        home_90=outcome.home_90,
        away_90=outcome.away_90,
        settlement_parameter_decimal=leg.settlement_parameter_decimal,
        crs_exact_codes=leg.crs_exact_codes,
    )
    return SettlementLegPlan(
        ticket_note_leg_id=leg.ticket_note_leg_id,
        outcome_revision_id=outcome.outcome_revision_id,
        result_disposition=outcome.result_disposition,
        market_result_code=grade.market_result_code,
        leg_grade=grade.leg_grade,
    )


__all__ = [
    "PayoutCashEntryPlan",
    "SettlementLegInput",
    "SettlementLegPlan",
    "SettlementNoteInput",
    "SettlementNotePlan",
    "SettlementOutcomeInput",
    "SettlementTicketInput",
    "TicketSettlementPlan",
    "ZucaiPrizeTierInput",
    "grade_ticket_settlement",
    "plan_payout_cash_entries",
]
