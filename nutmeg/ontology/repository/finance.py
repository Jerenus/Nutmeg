"""Finance & outcome persistence: budget, tickets, legs, ledger, outcomes, settlements.

Cash transactions store a **signed** amount (stake negative, payout positive), so
``ledger_balance`` is a plain SUM. Match outcomes are versioned; a correction adds
a version. Settlements are written only when an outcome exists.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_finance as sf


@dataclass(frozen=True, slots=True)
class CashAccountRow:
    account_id: str
    channel_scope: str
    currency: str
    status: str


@dataclass(frozen=True, slots=True)
class BudgetPolicyRow:
    budget_policy_id: str
    policy_version: str
    channel: str
    total_cap: float
    bucket_caps: dict[str, float]
    status: str
    effective_at: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProposalRow:
    proposal_id: str
    decision_session_id: str | None
    policy_version: str
    proposed_legs: list[dict[str, object]]
    proposed_stake: float
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class TicketRow:
    ticket_id: str
    channel: str
    proposal_id: str | None
    approved_at: str
    status: str
    structure: str
    total_stake: float
    currency: str
    account_id: str


@dataclass(frozen=True, slots=True)
class BetLegRow:
    bet_leg_id: str
    ticket_id: str
    forecast_revision_id: str
    match_id: str
    market_definition_id: str
    selection_id: str
    entry_quote_id: str | None
    line: str | None
    stake_share: float | None
    entry_odds: float | None = None


@dataclass(frozen=True, slots=True)
class CashTransactionRow:
    transaction_id: str
    account_id: str
    ticket_id: str | None
    ticket_settlement_id: str | None
    kind: str
    amount: float
    occurred_at: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OutcomeRow:
    outcome_id: str
    match_id: str
    version: int
    score_90: str
    score_aet: str | None
    penalties: str | None
    status: str
    source_artifact_retrieval_ids: list[str]
    recorded_at: str
    supersedes_outcome_id: str | None


@dataclass(frozen=True, slots=True)
class BetLegSettlementRow:
    bet_leg_settlement_id: str
    bet_leg_id: str
    outcome_id: str
    grade: str
    hit: int | None
    settlement_method_version: str


@dataclass(frozen=True, slots=True)
class TicketSettlementRow:
    ticket_settlement_id: str
    ticket_id: str
    settled_at: str
    status: str
    stake_amount: float
    payout_amount: float
    pnl_amount: float
    bet_leg_settlement_ids: list[str]
    settlement_method_version: str


class FinanceRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def ensure_account(self, row: CashAccountRow) -> None:
        existing = self._connection.execute(
            select(sf.cash_accounts.c.account_id).where(
                sf.cash_accounts.c.account_id == row.account_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        self._connection.execute(
            insert(sf.cash_accounts).values(
                account_id=row.account_id, channel_scope=row.channel_scope,
                currency=row.currency, status=row.status,
            )
        )

    def insert_budget_policy(self, row: BudgetPolicyRow) -> None:
        self._connection.execute(
            insert(sf.budget_policies).values(
                budget_policy_id=row.budget_policy_id, policy_version=row.policy_version,
                channel=row.channel, total_cap=row.total_cap,
                bucket_caps_json=canonical_json(row.bucket_caps), status=row.status,
                effective_at=row.effective_at, created_at=row.created_at,
            )
        )

    def active_budget_policy(self, channel: str) -> BudgetPolicyRow | None:
        row = (
            self._connection.execute(
                select(sf.budget_policies)
                .where(sf.budget_policies.c.channel == channel,
                       sf.budget_policies.c.status == 'active')
                .order_by(sf.budget_policies.c.effective_at.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return BudgetPolicyRow(
            budget_policy_id=row['budget_policy_id'], policy_version=row['policy_version'],
            channel=row['channel'], total_cap=row['total_cap'],
            bucket_caps=json.loads(row['bucket_caps_json']), status=row['status'],
            effective_at=row['effective_at'], created_at=row['created_at'],
        )

    def insert_proposal(self, row: ProposalRow) -> None:
        self._connection.execute(
            insert(sf.ticket_proposals).values(
                proposal_id=row.proposal_id, decision_session_id=row.decision_session_id,
                policy_version=row.policy_version,
                proposed_legs_json=canonical_json(row.proposed_legs),
                proposed_stake=row.proposed_stake, status=row.status, created_at=row.created_at,
            )
        )

    def insert_ticket(self, row: TicketRow) -> None:
        self._connection.execute(
            insert(sf.tickets).values(
                ticket_id=row.ticket_id, channel=row.channel, proposal_id=row.proposal_id,
                approved_at=row.approved_at, status=row.status, structure=row.structure,
                total_stake=row.total_stake, currency=row.currency, account_id=row.account_id,
            )
        )

    def insert_bet_leg(self, row: BetLegRow) -> None:
        self._connection.execute(
            insert(sf.bet_legs).values(
                bet_leg_id=row.bet_leg_id, ticket_id=row.ticket_id,
                forecast_revision_id=row.forecast_revision_id, match_id=row.match_id,
                market_definition_id=row.market_definition_id, selection_id=row.selection_id,
                entry_quote_id=row.entry_quote_id, line=row.line, stake_share=row.stake_share,
                entry_odds=row.entry_odds,
            )
        )

    def bet_leg_ids(self, ticket_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(sf.bet_legs.c.bet_leg_id).where(sf.bet_legs.c.ticket_id == ticket_id)
        ).scalars().all()
        return tuple(rows)

    def bet_legs_for(self, ticket_id: str) -> list[BetLegRow]:
        rows = (
            self._connection.execute(
                select(sf.bet_legs).where(sf.bet_legs.c.ticket_id == ticket_id)
            )
            .mappings()
            .all()
        )
        return [
            BetLegRow(
                bet_leg_id=r['bet_leg_id'], ticket_id=r['ticket_id'],
                forecast_revision_id=r['forecast_revision_id'], match_id=r['match_id'],
                market_definition_id=r['market_definition_id'], selection_id=r['selection_id'],
                entry_quote_id=r['entry_quote_id'], line=r['line'], stake_share=r['stake_share'],
                entry_odds=r['entry_odds'],
            )
            for r in rows
        ]

    def tickets_for_match(self, match_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(sf.bet_legs.c.ticket_id).where(sf.bet_legs.c.match_id == match_id).distinct()
        ).scalars().all()
        return tuple(rows)

    def insert_cash_transaction(self, row: CashTransactionRow) -> None:
        self._connection.execute(
            insert(sf.cash_transactions).values(
                transaction_id=row.transaction_id, account_id=row.account_id,
                ticket_id=row.ticket_id, ticket_settlement_id=row.ticket_settlement_id,
                kind=row.kind, amount=row.amount, occurred_at=row.occurred_at,
                idempotency_key=row.idempotency_key,
            )
        )

    def ledger_balance(self, account_id: str) -> float:
        value = self._connection.execute(
            select(func.sum(sf.cash_transactions.c.amount)).where(
                sf.cash_transactions.c.account_id == account_id
            )
        ).scalar_one_or_none()
        return float(value) if value is not None else 0.0

    def insert_outcome(self, row: OutcomeRow) -> None:
        self._connection.execute(
            insert(sf.match_outcomes).values(
                outcome_id=row.outcome_id, match_id=row.match_id, version=row.version,
                score_90=row.score_90, score_aet=row.score_aet, penalties=row.penalties,
                status=row.status,
                source_artifact_retrieval_ids_json=canonical_json(row.source_artifact_retrieval_ids),
                recorded_at=row.recorded_at, supersedes_outcome_id=row.supersedes_outcome_id,
            )
        )

    def max_outcome_version(self, match_id: str) -> int:
        value = self._connection.execute(
            select(func.max(sf.match_outcomes.c.version)).where(
                sf.match_outcomes.c.match_id == match_id
            )
        ).scalar_one_or_none()
        return int(value) if value is not None else 0

    def current_outcome(self, match_id: str) -> OutcomeRow | None:
        row = (
            self._connection.execute(
                select(sf.match_outcomes)
                .where(sf.match_outcomes.c.match_id == match_id)
                .order_by(sf.match_outcomes.c.version.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return OutcomeRow(
            outcome_id=row['outcome_id'], match_id=row['match_id'], version=row['version'],
            score_90=row['score_90'], score_aet=row['score_aet'], penalties=row['penalties'],
            status=row['status'],
            source_artifact_retrieval_ids=json.loads(row['source_artifact_retrieval_ids_json']),
            recorded_at=row['recorded_at'], supersedes_outcome_id=row['supersedes_outcome_id'],
        )

    def insert_bet_leg_settlement(self, row: BetLegSettlementRow) -> None:
        self._connection.execute(
            insert(sf.bet_leg_settlements).values(
                bet_leg_settlement_id=row.bet_leg_settlement_id, bet_leg_id=row.bet_leg_id,
                outcome_id=row.outcome_id, grade=row.grade, hit=row.hit,
                settlement_method_version=row.settlement_method_version,
            )
        )

    def insert_ticket_settlement(self, row: TicketSettlementRow) -> None:
        self._connection.execute(
            insert(sf.ticket_settlements).values(
                ticket_settlement_id=row.ticket_settlement_id, ticket_id=row.ticket_id,
                settled_at=row.settled_at, status=row.status, stake_amount=row.stake_amount,
                payout_amount=row.payout_amount, pnl_amount=row.pnl_amount,
                bet_leg_settlement_ids_json=canonical_json(row.bet_leg_settlement_ids),
                settlement_method_version=row.settlement_method_version,
            )
        )

    def count_tickets(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sf.tickets)
        ).scalar_one()

    def count_settlements(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sf.ticket_settlements)
        ).scalar_one()
