"""Market Core tables on the shared ontology MetaData.

Market definitions carry an explicit settlement_scope (regular time vs incl.
extra time / penalties), so an hhad 3-way is never silently treated as an Asian
handicap. Quotes are prices; snapshots are the deterministically de-vigged fair
distribution with method versioning. `market_quotes.artifact_retrieval_id` is
nullable so a replay from a pre-parsed snapshot still records quotes; live ingest
always sets it.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    text,
)

from nutmeg.ontology.repository.schema import metadata

market_definitions = Table(
    'market_definitions',
    metadata,
    Column('market_definition_id', Text, primary_key=True),
    Column('market_kind', Text, nullable=False),
    Column('settlement_scope', Text, nullable=False),
    Column('ordered', Integer, nullable=False, server_default=text('0')),
    Column('line_schema', Text, nullable=True),
    Column('outcome_schema_version', Text, nullable=False),
)

selection_definitions = Table(
    'selection_definitions',
    metadata,
    Column('selection_id', Text, primary_key=True),
    Column(
        'market_definition_id',
        Text,
        ForeignKey('market_definitions.market_definition_id', ondelete='RESTRICT'),
        nullable=False,
    ),
    Column('outcome_key', Text, nullable=False),
    Column('line', Text, nullable=True),
)

market_quotes = Table(
    'market_quotes',
    metadata,
    Column('quote_id', Text, primary_key=True),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'), nullable=False),
    Column(
        'market_definition_id',
        Text,
        ForeignKey('market_definitions.market_definition_id', ondelete='RESTRICT'),
        nullable=False,
    ),
    Column(
        'selection_id',
        Text,
        ForeignKey('selection_definitions.selection_id', ondelete='RESTRICT'),
        nullable=False,
    ),
    Column('provider', Text, nullable=False),
    Column('bookmaker', Text, nullable=True),
    Column('decimal_odds', Float, nullable=False),
    Column('captured_at', Text, nullable=False),
    Column(
        'artifact_retrieval_id',
        Text,
        ForeignKey('artifact_retrievals.artifact_retrieval_id', ondelete='RESTRICT'),
        nullable=True,
    ),
    Column('quote_status', Text, nullable=False),
    CheckConstraint('decimal_odds > 1.0', name='ck_market_quotes_odds'),
)

market_snapshots = Table(
    'market_snapshots',
    metadata,
    Column('market_snapshot_id', Text, primary_key=True),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'), nullable=False),
    Column(
        'market_definition_id',
        Text,
        ForeignKey('market_definitions.market_definition_id', ondelete='RESTRICT'),
        nullable=False,
    ),
    Column('snapshot_kind', Text, nullable=False),
    Column('as_of', Text, nullable=False),
    Column('fair_distribution_json', Text, nullable=False),
    Column('devig_method', Text, nullable=False),
    Column('method_version', Text, nullable=False),
    Column('source_coverage_json', Text, nullable=False),
    Column('freshness_json', Text, nullable=False),
    Column('disagreement_json', Text, nullable=False),
)

market_snapshot_quotes = Table(
    'market_snapshot_quotes',
    metadata,
    Column(
        'market_snapshot_id',
        Text,
        ForeignKey('market_snapshots.market_snapshot_id', ondelete='RESTRICT'),
        nullable=False,
    ),
    Column(
        'quote_id', Text, ForeignKey('market_quotes.quote_id', ondelete='RESTRICT'), nullable=False
    ),
    PrimaryKeyConstraint('market_snapshot_id', 'quote_id', name='pk_market_snapshot_quotes'),
)
