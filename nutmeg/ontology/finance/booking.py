"""Shared atomic writer for existing formal Ticket, BetLeg, and stake rows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nutmeg.ontology.finance.budget import validate_within_budget
from nutmeg.ontology.finance.models import TicketStatus, TransactionKind, mint_finance_id
from nutmeg.ontology.repository.finance import (
    BetLegRow,
    CashTransactionRow,
    TicketRow,
)

if TYPE_CHECKING:
    from nutmeg.ontology.actions.ticket_actions import LegInput


@dataclass(frozen=True, slots=True)
class BookingResult:
    ticket_id: str
    bet_leg_ids: tuple[str, ...]
    transaction_id: str | None


def assert_current_forecast(uow, leg: LegInput) -> None:
    series_id = uow.decision.ensure_series(leg.match_id, leg.market_definition_id)
    current = uow.decision.current_committed_revision(series_id)
    if current is None or current.forecast_revision_id != leg.forecast_revision_id:
        raise ValueError(
            f"leg forecast {leg.forecast_revision_id} is not the committed revision "
            f"for {leg.match_id}/{leg.market_definition_id}"
        )


def book_ticket_rows(
    uow,
    *,
    channel: str,
    account_id: str,
    proposal_id: str | None,
    legs: list[LegInput],
    at: str,
    stake_idempotency_key: str,
) -> BookingResult:
    for leg in legs:
        assert_current_forecast(uow, leg)
    policy = uow.finance.active_budget_policy(channel)
    if policy is not None:
        validate_within_budget(
            policy.total_cap,
            policy.bucket_caps,
            [{"bucket": leg.bucket, "stake": leg.stake} for leg in legs],
        )
    total_stake = sum(leg.stake for leg in legs)
    ticket_id = mint_finance_id("tk")
    uow.finance.insert_ticket(
        TicketRow(
            ticket_id=ticket_id,
            channel=channel,
            proposal_id=proposal_id,
            approved_at=at,
            status=TicketStatus.APPROVED.value,
            structure="single" if len(legs) == 1 else "parlay",
            total_stake=total_stake,
            currency="CNY",
            account_id=account_id,
        )
    )
    bet_leg_ids: list[str] = []
    for leg in legs:
        bet_leg_id = mint_finance_id("bl")
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
                entry_odds=leg.entry_odds,
            )
        )
        bet_leg_ids.append(bet_leg_id)
    transaction_id = None
    if total_stake > 0:
        transaction_id = mint_finance_id("cx")
        uow.finance.insert_cash_transaction(
            CashTransactionRow(
                transaction_id=transaction_id,
                account_id=account_id,
                ticket_id=ticket_id,
                ticket_settlement_id=None,
                kind=TransactionKind.STAKE.value,
                amount=-total_stake,
                occurred_at=at,
                idempotency_key=stake_idempotency_key,
            )
        )
    return BookingResult(ticket_id, tuple(bet_leg_ids), transaction_id)
