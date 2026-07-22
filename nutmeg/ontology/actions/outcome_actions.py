"""Outcome Actions: record / correct a match outcome, settle a ticket.

Outcomes are versioned truth: a correction adds a new version that supersedes the
prior one — no row is ever overwritten, so the audit keeps both. Settlement reads
the *current* outcome; if none exists it writes nothing and returns ``settled=False``
(a missing result is never a pending loss). All three are deterministic_system.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.finance.models import (
    OutcomeStatus,
    SettlementGrade,
    TicketStatus,
    TransactionKind,
    mint_finance_id,
)
from nutmeg.ontology.finance.settlement import grade_had
from nutmeg.ontology.repository.finance import (
    BetLegSettlementRow,
    CashTransactionRow,
    OutcomeRow,
    TicketSettlementRow,
)

_SETTLEMENT_METHOD_VERSION = 'had-3way-v1'
# Odds-faithful settlement: payout = stake × Π(entry_odds of WIN legs); VOID/PUSH legs
# contribute 1.0 (a push, per sporttery parlay convention — all legs void refunds the
# stake); any LOSS pays 0. The legacy flat ×2 multiplier survives ONLY for legs written
# before migration 9 (entry_odds NULL) and is auditable via settlement_method_version.
_SETTLEMENT_METHOD_ODDS = 'odds-faithful-v1'
_PLACEHOLDER_WIN_MULTIPLIER = 2.0
# Only the had 3-way market is graded in 3B; any other market is graded VOID (hit
# unknown) rather than silently mis-read as a loss. hhad/ttg/crs grading is a
# documented 3B follow-on.
_HAD_MARKET_ID = 'md-had'


def _grade_leg(
    market_definition_id: str, selection_id: str, home: int, away: int
) -> tuple[SettlementGrade, int | None]:
    if market_definition_id != _HAD_MARKET_ID:
        return SettlementGrade.VOID, None
    grade = grade_had(selection_id.rsplit('-', 1)[-1], home, away)
    return grade, 1 if grade is SettlementGrade.WIN else 0


@dataclass(frozen=True, slots=True)
class RecordOutcomeRequest:
    match_id: str
    score_90: str
    status: str
    source_artifact_retrieval_ids: list[str]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    score_aet: str | None = None
    penalties: str | None = None


@dataclass(frozen=True, slots=True)
class SettleTicketRequest:
    ticket_id: str
    match_id: str
    account_id: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class SettleTicketResult:
    outcome: ActionOutcome
    settled: bool


def _score_parts(score: str) -> tuple[int, int]:
    home, away = score.split('-')
    return int(home), int(away)


class OutcomeActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def record_outcome(self, request: RecordOutcomeRequest) -> ActionOutcome:
        return self._write_outcome(request, 'record_outcome', correcting=False)

    def correct_outcome(self, request: RecordOutcomeRequest) -> ActionOutcome:
        return self._write_outcome(request, 'correct_outcome', correcting=True)

    def _write_outcome(
        self, request: RecordOutcomeRequest, action_type: str, correcting: bool
    ) -> ActionOutcome:
        command = ActionCommand.create(
            action_type=action_type,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={'match_id': request.match_id, 'score_90': request.score_90},
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            at = request.requested_at.astimezone(UTC).isoformat()
            current = uow.finance.current_outcome(request.match_id)
            if correcting and current is None:
                raise ValueError('no outcome to correct')
            version = uow.finance.max_outcome_version(request.match_id) + 1
            supersedes = current.outcome_id if correcting and current is not None else None
            outcome_id = mint_finance_id('mo')
            uow.finance.insert_outcome(
                OutcomeRow(
                    outcome_id=outcome_id,
                    match_id=request.match_id,
                    version=version,
                    score_90=request.score_90,
                    score_aet=request.score_aet,
                    penalties=request.penalties,
                    status=request.status,
                    source_artifact_retrieval_ids=request.source_artifact_retrieval_ids,
                    recorded_at=at,
                    supersedes_outcome_id=supersedes,
                )
            )
            return (ObjectRef('match_outcome', outcome_id),)

        return self._action_service.execute(command, handler)

    def settle_ticket(self, request: SettleTicketRequest) -> SettleTicketResult:
        command = ActionCommand.create(
            action_type='settle_ticket',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={'ticket_id': request.ticket_id, 'match_id': request.match_id},
            requested_at=request.requested_at,
        )
        settled_flag = {'value': False}

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            outcome = uow.finance.current_outcome(request.match_id)
            if outcome is None:
                return ()  # missing result — never a pending settlement
            settled_flag['value'] = True
            at = request.requested_at.astimezone(UTC).isoformat()
            home, away = _score_parts(outcome.score_90)
            legs = uow.finance.bet_legs_for(request.ticket_id)
            odds_known = bool(legs) and all(leg.entry_odds is not None for leg in legs)
            method = _SETTLEMENT_METHOD_ODDS if odds_known else _SETTLEMENT_METHOD_VERSION
            leg_settlement_ids: list[ObjectRef] = []
            all_win = True
            any_loss = False
            odds_product = 1.0
            for leg in legs:
                grade, hit = _grade_leg(leg.market_definition_id, leg.selection_id, home, away)
                if grade is not SettlementGrade.WIN:
                    all_win = False
                if grade is SettlementGrade.LOSS:
                    any_loss = True
                elif grade is SettlementGrade.WIN and odds_known:
                    odds_product *= float(leg.entry_odds)
                # VOID/PUSH legs contribute 1.0 to the product (a push)
                settlement_id = mint_finance_id('bls')
                uow.finance.insert_bet_leg_settlement(
                    BetLegSettlementRow(
                        bet_leg_settlement_id=settlement_id,
                        bet_leg_id=leg.bet_leg_id,
                        outcome_id=outcome.outcome_id,
                        grade=grade.value,
                        hit=hit,
                        settlement_method_version=method,
                    )
                )
                leg_settlement_ids.append(ObjectRef('bet_leg_settlement', settlement_id))
            stake = sum(leg.stake_share or 0.0 for leg in legs)
            if odds_known:
                payout = 0.0 if any_loss or not legs else round(stake * odds_product, 2)
            else:
                # legacy pre-migration-9 legs: flat multiplier, VOID blocks payout
                payout = stake * _PLACEHOLDER_WIN_MULTIPLIER if all_win and legs else 0.0
            pnl = round(payout - stake, 2)
            ticket_settlement_id = mint_finance_id('ts')
            uow.finance.insert_ticket_settlement(
                TicketSettlementRow(
                    ticket_settlement_id=ticket_settlement_id,
                    ticket_id=request.ticket_id,
                    settled_at=at,
                    status=TicketStatus.SETTLED.value,
                    stake_amount=stake,
                    payout_amount=payout,
                    pnl_amount=pnl,
                    bet_leg_settlement_ids=[ref.object_id for ref in leg_settlement_ids],
                    settlement_method_version=method,
                )
            )
            refs: list[ObjectRef] = [
                ObjectRef('ticket_settlement', ticket_settlement_id),
                *leg_settlement_ids,
            ]
            if payout > 0:
                transaction_id = mint_finance_id('cx')
                uow.finance.insert_cash_transaction(
                    CashTransactionRow(
                        transaction_id=transaction_id,
                        account_id=request.account_id,
                        ticket_id=request.ticket_id,
                        ticket_settlement_id=ticket_settlement_id,
                        kind=TransactionKind.PAYOUT.value,
                        amount=payout,
                        occurred_at=at,
                        idempotency_key=f'{ticket_settlement_id}:payout',
                    )
                )
                refs.append(ObjectRef('cash_transaction', transaction_id))
            return tuple(refs)

        outcome = self._action_service.execute(command, handler)
        return SettleTicketResult(outcome=outcome, settled=settled_flag['value'])


# OutcomeStatus is re-exported for callers building final/provisional records.
__all__ = [
    'OutcomeActions',
    'OutcomeStatus',
    'RecordOutcomeRequest',
    'SettleTicketRequest',
    'SettleTicketResult',
]
