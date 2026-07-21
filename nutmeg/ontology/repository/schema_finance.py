"""Finance & outcome Core tables on the shared ontology MetaData.

Every BetLeg references a committed ForecastRevision and its entry quote; ticket
approval writes ticket + legs + a stake cash transaction in one transaction.
Match outcomes are versioned (corrections add a version, never overwrite).
Settlements are produced only when an outcome is sufficient.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from nutmeg.ontology.repository.schema import metadata

cash_accounts = Table(
    'cash_accounts',
    metadata,
    Column('account_id', Text, primary_key=True),
    Column('channel_scope', Text, nullable=False),
    Column('currency', Text, nullable=False),
    Column('status', Text, nullable=False),
)

budget_policies = Table(
    'budget_policies',
    metadata,
    Column('budget_policy_id', Text, primary_key=True),
    Column('policy_version', Text, nullable=False),
    Column('channel', Text, nullable=False),
    Column('total_cap', Float, nullable=False),
    Column('bucket_caps_json', Text, nullable=False),
    Column('status', Text, nullable=False),
    Column('effective_at', Text, nullable=False),
    Column('created_at', Text, nullable=False),
)

ticket_proposals = Table(
    'ticket_proposals',
    metadata,
    Column('proposal_id', Text, primary_key=True),
    Column('decision_session_id', Text, nullable=True),
    Column('policy_version', Text, nullable=False),
    Column('proposed_legs_json', Text, nullable=False),
    Column('proposed_stake', Float, nullable=False),
    Column('status', Text, nullable=False),
    Column('created_at', Text, nullable=False),
)

tickets = Table(
    'tickets',
    metadata,
    Column('ticket_id', Text, primary_key=True),
    Column('channel', Text, nullable=False),
    Column('proposal_id', Text,
           ForeignKey('ticket_proposals.proposal_id', ondelete='RESTRICT'), nullable=True),
    Column('approved_at', Text, nullable=False),
    Column('status', Text, nullable=False),
    Column('structure', Text, nullable=False),
    Column('total_stake', Float, nullable=False),
    Column('currency', Text, nullable=False),
    Column('account_id', Text,
           ForeignKey('cash_accounts.account_id', ondelete='RESTRICT'), nullable=False),
)

bet_legs = Table(
    'bet_legs',
    metadata,
    Column('bet_leg_id', Text, primary_key=True),
    Column('ticket_id', Text, ForeignKey('tickets.ticket_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('forecast_revision_id', Text,
           ForeignKey('forecast_revisions.forecast_revision_id', ondelete='RESTRICT'),
           nullable=False),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'), nullable=False),
    Column('market_definition_id', Text,
           ForeignKey('market_definitions.market_definition_id', ondelete='RESTRICT'),
           nullable=False),
    Column('selection_id', Text,
           ForeignKey('selection_definitions.selection_id', ondelete='RESTRICT'), nullable=False),
    Column('entry_quote_id', Text,
           ForeignKey('market_quotes.quote_id', ondelete='RESTRICT'), nullable=True),
    Column('line', Text, nullable=True),
    Column('stake_share', Float, nullable=True),
)

cash_transactions = Table(
    'cash_transactions',
    metadata,
    Column('transaction_id', Text, primary_key=True),
    Column('account_id', Text,
           ForeignKey('cash_accounts.account_id', ondelete='RESTRICT'), nullable=False, index=True),
    Column('ticket_id', Text, ForeignKey('tickets.ticket_id', ondelete='RESTRICT'), nullable=True),
    Column('ticket_settlement_id', Text, nullable=True),
    Column('kind', Text, nullable=False),
    Column('amount', Float, nullable=False),
    Column('occurred_at', Text, nullable=False),
    Column('idempotency_key', Text, nullable=False, unique=True),
)

match_outcomes = Table(
    'match_outcomes',
    metadata,
    Column('outcome_id', Text, primary_key=True),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('version', Integer, nullable=False),
    Column('score_90', Text, nullable=False),
    Column('score_aet', Text, nullable=True),
    Column('penalties', Text, nullable=True),
    Column('status', Text, nullable=False),
    Column('source_artifact_retrieval_ids_json', Text, nullable=False),
    Column('recorded_at', Text, nullable=False),
    Column('supersedes_outcome_id', Text, nullable=True),
    UniqueConstraint('match_id', 'version', name='uq_match_outcomes_match_version'),
)

bet_leg_settlements = Table(
    'bet_leg_settlements',
    metadata,
    Column('bet_leg_settlement_id', Text, primary_key=True),
    Column('bet_leg_id', Text, ForeignKey('bet_legs.bet_leg_id', ondelete='RESTRICT'),
           nullable=False),
    Column('outcome_id', Text, ForeignKey('match_outcomes.outcome_id', ondelete='RESTRICT'),
           nullable=False),
    Column('grade', Text, nullable=False),
    Column('hit', Integer, nullable=True),
    Column('settlement_method_version', Text, nullable=False),
)

ticket_settlements = Table(
    'ticket_settlements',
    metadata,
    Column('ticket_settlement_id', Text, primary_key=True),
    Column('ticket_id', Text, ForeignKey('tickets.ticket_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('settled_at', Text, nullable=False),
    Column('status', Text, nullable=False),
    Column('stake_amount', Float, nullable=False),
    Column('payout_amount', Float, nullable=False),
    Column('pnl_amount', Float, nullable=False),
    Column('bet_leg_settlement_ids_json', Text, nullable=False),
    Column('settlement_method_version', Text, nullable=False),
)
