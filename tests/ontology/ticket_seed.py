"""Seed approved kernel tickets for the reconcile/settle tests.

The propose/approve/express Actions that booked tickets were retired on
2026-10-08 (no production caller). Settling the tickets already in the kernel is
still live (``decision-settle`` runs it daily), so these tests write the same
rows the retired booking path wrote: one approved Ticket, its BetLegs and the
single stake CashTransaction.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, insert, select

from nutmeg.ontology.finance.models import mint_finance_id
from nutmeg.ontology.repository import schema_finance as sf


@dataclass(frozen=True, slots=True)
class Leg:
    match_id: str
    forecast_revision_id: str
    stake: float
    entry_odds: float | None
    selection_id: str = "sel-had-home"
    market_definition_id: str = "md-had"
    line: str | None = None


def seed_account(engine, account_id: str = "acct-jczq", channel: str = "jczq") -> None:
    with engine.begin() as connection:
        connection.execute(insert(sf.cash_accounts).values(
            account_id=account_id, channel_scope=channel, currency="CNY", status="active"))


def seed_ticket(
    engine,
    legs: list[Leg],
    *,
    at: str,
    account_id: str = "acct-jczq",
    channel: str = "jczq",
) -> str:
    ticket_id = mint_finance_id("tk")
    total = sum(leg.stake for leg in legs)
    with engine.begin() as connection:
        connection.execute(insert(sf.tickets).values(
            ticket_id=ticket_id, channel=channel, proposal_id=None, approved_at=at,
            status="approved", structure="single" if len(legs) == 1 else "parlay",
            total_stake=total, currency="CNY", account_id=account_id))
        for leg in legs:
            connection.execute(insert(sf.bet_legs).values(
                bet_leg_id=mint_finance_id("bl"), ticket_id=ticket_id,
                forecast_revision_id=leg.forecast_revision_id, match_id=leg.match_id,
                market_definition_id=leg.market_definition_id,
                selection_id=leg.selection_id, entry_quote_id=None, line=leg.line,
                stake_share=leg.stake, entry_odds=leg.entry_odds))
        connection.execute(insert(sf.cash_transactions).values(
            transaction_id=mint_finance_id("cx"), account_id=account_id,
            ticket_id=ticket_id, ticket_settlement_id=None, kind="stake",
            amount=-total, occurred_at=at, idempotency_key=f"{ticket_id}:stake"))
    return ticket_id


def ledger_balance(engine, account_id: str = "acct-jczq") -> float:
    with engine.connect() as connection:
        value = connection.execute(
            select(func.sum(sf.cash_transactions.c.amount)).where(
                sf.cash_transactions.c.account_id == account_id)
        ).scalar_one_or_none()
    return float(value) if value is not None else 0.0
