"""Ticket Actions: propose / approve a ticket, record a cash transaction.

Every bet leg must reference the *current committed* forecast revision for its
match+market (the belief the ticket expresses). ``approve_ticket`` writes the
Ticket, its BetLegs, and the single stake CashTransaction in one atomic handler,
after checking the ¥400 budget. The budget is a ceiling — an empty slate never
reaches approve (the express facade short-circuits).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.finance.budget import validate_within_budget
from nutmeg.ontology.finance.models import (
    ProposalStatus,
    TicketStatus,
    TransactionKind,
    mint_finance_id,
)
from nutmeg.ontology.repository.finance import (
    BetLegRow,
    CashTransactionRow,
    ProposalRow,
    TicketRow,
)


@dataclass(frozen=True, slots=True)
class LegInput:
    match_id: str
    market_definition_id: str
    selection_id: str
    forecast_revision_id: str
    bucket: str
    stake: float
    entry_quote_id: str | None = None
    line: str | None = None


@dataclass(frozen=True, slots=True)
class ProposeTicketRequest:
    channel: str
    decision_session_id: str | None
    legs: list[LegInput]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ApproveTicketRequest:
    channel: str
    account_id: str
    proposal_id: str | None
    legs: list[LegInput]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class RecordCashTransactionRequest:
    account_id: str
    kind: str
    amount: float
    idempotency_key: str
    actor_id: str
    actor_role: ActorRole
    requested_at: datetime
    ticket_id: str | None = None


def _leg_dict(leg: LegInput) -> dict[str, object]:
    return {
        'match_id': leg.match_id,
        'market_definition_id': leg.market_definition_id,
        'selection_id': leg.selection_id,
        'forecast_revision_id': leg.forecast_revision_id,
        'bucket': leg.bucket,
        'stake': leg.stake,
        'entry_quote_id': leg.entry_quote_id,
        'line': leg.line,
    }


def _assert_committed(uow, leg: LegInput) -> None:
    series_id = uow.decision.ensure_series(leg.match_id, leg.market_definition_id)
    current = uow.decision.current_committed_revision(series_id)
    if current is None or current.forecast_revision_id != leg.forecast_revision_id:
        raise ValueError(
            f'leg forecast {leg.forecast_revision_id} is not the committed revision '
            f'for {leg.match_id}/{leg.market_definition_id}'
        )


class TicketActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def propose_ticket(self, request: ProposeTicketRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type='propose_ticket',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={'channel': request.channel, 'leg_count': len(request.legs)},
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            for leg in request.legs:
                _assert_committed(uow, leg)
            at = request.requested_at.astimezone(UTC).isoformat()
            proposal_id = mint_finance_id('tp')
            uow.finance.insert_proposal(
                ProposalRow(
                    proposal_id=proposal_id,
                    decision_session_id=request.decision_session_id,
                    policy_version=_command.policy_version,
                    proposed_legs=[_leg_dict(leg) for leg in request.legs],
                    proposed_stake=sum(leg.stake for leg in request.legs),
                    status=ProposalStatus.PROPOSED.value,
                    created_at=at,
                )
            )
            return (ObjectRef('ticket_proposal', proposal_id),)

        return self._action_service.execute(command, handler)

    def approve_ticket(self, request: ApproveTicketRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type='approve_ticket',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={'channel': request.channel, 'leg_count': len(request.legs)},
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            for leg in request.legs:
                _assert_committed(uow, leg)
            policy = uow.finance.active_budget_policy(request.channel)
            if policy is not None:
                validate_within_budget(
                    policy.total_cap,
                    policy.bucket_caps,
                    [{'bucket': leg.bucket, 'stake': leg.stake} for leg in request.legs],
                )
            at = request.requested_at.astimezone(UTC).isoformat()
            total_stake = sum(leg.stake for leg in request.legs)
            ticket_id = mint_finance_id('tk')
            structure = 'single' if len(request.legs) == 1 else 'parlay'
            uow.finance.insert_ticket(
                TicketRow(
                    ticket_id=ticket_id,
                    channel=request.channel,
                    proposal_id=request.proposal_id,
                    approved_at=at,
                    status=TicketStatus.APPROVED.value,
                    structure=structure,
                    total_stake=total_stake,
                    currency='CNY',
                    account_id=request.account_id,
                )
            )
            refs: list[ObjectRef] = [ObjectRef('ticket', ticket_id)]
            for leg in request.legs:
                bet_leg_id = mint_finance_id('bl')
                uow.finance.insert_bet_leg(
                    BetLegRow(
                        bet_leg_id=bet_leg_id,
                        ticket_id=ticket_id,
                        forecast_revision_id=leg.forecast_revision_id,
                        match_id=leg.match_id,
                        market_definition_id=leg.market_definition_id,
                        selection_id=leg.selection_id,
                        entry_quote_id=leg.entry_quote_id,
                        line=leg.line,
                        stake_share=leg.stake,
                    )
                )
                refs.append(ObjectRef('bet_leg', bet_leg_id))
            if total_stake > 0:
                transaction_id = mint_finance_id('cx')
                uow.finance.insert_cash_transaction(
                    CashTransactionRow(
                        transaction_id=transaction_id,
                        account_id=request.account_id,
                        ticket_id=ticket_id,
                        ticket_settlement_id=None,
                        kind=TransactionKind.STAKE.value,
                        amount=-total_stake,
                        occurred_at=at,
                        idempotency_key=f'{ticket_id}:stake',
                    )
                )
                refs.append(ObjectRef('cash_transaction', transaction_id))
            return tuple(refs)

        return self._action_service.execute(command, handler)

    def record_cash_transaction(self, request: RecordCashTransactionRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type='record_cash_transaction',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={'account_id': request.account_id, 'kind': request.kind},
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            at = request.requested_at.astimezone(UTC).isoformat()
            transaction_id = mint_finance_id('cx')
            uow.finance.insert_cash_transaction(
                CashTransactionRow(
                    transaction_id=transaction_id,
                    account_id=request.account_id,
                    ticket_id=request.ticket_id,
                    ticket_settlement_id=None,
                    kind=request.kind,
                    amount=request.amount,
                    occurred_at=at,
                    idempotency_key=request.idempotency_key,
                )
            )
            return (ObjectRef('cash_transaction', transaction_id),)

        return self._action_service.execute(command, handler)
