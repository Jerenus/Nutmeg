"""Decision (belief) Core tables on the shared ontology MetaData.

EvidenceBundle freezes an as-of input set (prior snapshot + verified observations
+ caveats) with a content hash. ForecastRevision anchors prior to a market
snapshot and records belief with a per-factor delta decomposition. One current
committed revision per series is enforced in the application layer + optimistic
concurrency. ``decision_session_id`` is a soft workflow grouping (nullable, no
FK) so standalone forecasts need not open a session.
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

decision_sessions = Table(
    'decision_sessions',
    metadata,
    Column('decision_session_id', Text, primary_key=True),
    Column('opened_at', Text, nullable=False),
    Column('operator_id', Text, nullable=False),
    Column('cutoff_at', Text, nullable=False),
    Column('scope_json', Text, nullable=False),
    Column('status', Text, nullable=False),
    Column('closed_at', Text, nullable=True),
)

evidence_bundles = Table(
    'evidence_bundles',
    metadata,
    Column('evidence_bundle_id', Text, primary_key=True),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'), nullable=False),
    Column('decision_session_id', Text, nullable=True),
    Column('frozen_at', Text, nullable=False),
    Column('information_cutoff_at', Text, nullable=False),
    Column('market_snapshot_id', Text,
           ForeignKey('market_snapshots.market_snapshot_id', ondelete='RESTRICT'), nullable=True),
    Column('prior_distribution_json', Text, nullable=False),
    Column('identity_resolution_version', Text, nullable=True),
    Column('source_coverage_json', Text, nullable=False),
    Column('freshness_json', Text, nullable=False),
    Column('content_hash', Text, nullable=False),
)

evidence_bundle_items = Table(
    'evidence_bundle_items',
    metadata,
    Column('item_id', Text, primary_key=True),
    Column('evidence_bundle_id', Text,
           ForeignKey('evidence_bundles.evidence_bundle_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('item_type', Text, nullable=False),
    Column('observation_id', Text, nullable=True),
    Column('claim_id', Text, nullable=True),
)

forecast_series = Table(
    'forecast_series',
    metadata,
    Column('forecast_series_id', Text, primary_key=True),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'), nullable=False),
    Column('market_definition_id', Text,
           ForeignKey('market_definitions.market_definition_id', ondelete='RESTRICT'),
           nullable=False),
    UniqueConstraint('match_id', 'market_definition_id', name='uq_forecast_series_match_market'),
)

forecast_revisions = Table(
    'forecast_revisions',
    metadata,
    Column('forecast_revision_id', Text, primary_key=True),
    Column('forecast_series_id', Text,
           ForeignKey('forecast_series.forecast_series_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('decision_session_id', Text, nullable=True),
    Column('revision_no', Integer, nullable=False),
    Column('status', Text, nullable=False),
    Column('made_at', Text, nullable=False),
    Column('information_cutoff_at', Text, nullable=True),
    Column('prior_snapshot_id', Text,
           ForeignKey('market_snapshots.market_snapshot_id', ondelete='RESTRICT'), nullable=True),
    Column('prior_distribution_json', Text, nullable=False),
    Column('belief_distribution_json', Text, nullable=False),
    Column('evidence_bundle_id', Text,
           ForeignKey('evidence_bundles.evidence_bundle_id', ondelete='RESTRICT'), nullable=True),
    Column('falsifier', Text, nullable=True),
    Column('actor_id', Text, nullable=False),
    Column('model_name', Text, nullable=True),
    Column('model_version', Text, nullable=True),
    Column('policy_version', Text, nullable=False),
    Column('commitment_tier', Text, nullable=False),
    Column('evidence_coverage', Float, nullable=True),
    Column('evidence_quality', Float, nullable=True),
    Column('forecast_stability', Float, nullable=True),
    Column('supersedes_revision_id', Text, nullable=True),
    UniqueConstraint('forecast_series_id', 'revision_no', name='uq_forecast_revisions_series_no'),
)

factor_families = Table(
    'factor_families',
    metadata,
    Column('factor_family_id', Text, primary_key=True),
    Column('name', Text, nullable=False),
    Column('definition', Text, nullable=True),
)

factor_definitions = Table(
    'factor_definitions',
    metadata,
    Column('factor_definition_id', Text, primary_key=True),
    Column('factor_family_id', Text,
           ForeignKey('factor_families.factor_family_id', ondelete='RESTRICT'), nullable=False),
    Column('version', Integer, nullable=False),
    Column('name', Text, nullable=False),
    Column('definition', Text, nullable=True),
    Column('scope', Text, nullable=True),
    Column('status', Text, nullable=False),
    Column('born_from_refs_json', Text, nullable=False),
    Column('valid_from', Text, nullable=False),
    Column('valid_to', Text, nullable=True),
    Column('policy_version', Text, nullable=False),
    UniqueConstraint('factor_family_id', 'version', name='uq_factor_definitions_family_version'),
)

factor_applications = Table(
    'factor_applications',
    metadata,
    Column('factor_application_id', Text, primary_key=True),
    Column('forecast_revision_id', Text,
           ForeignKey('forecast_revisions.forecast_revision_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    # Soft reference (no FK): a draft may cite a proposed factor before it is a
    # formal factor_definitions row; the lifecycle table tracks status separately.
    Column('factor_definition_id', Text, nullable=False),
    Column('scope_entity_ids_json', Text, nullable=False),
    Column('delta_distribution_json', Text, nullable=False),
    Column('supporting_observation_ids_json', Text, nullable=False),
    Column('note', Text, nullable=True),
)

scenarios = Table(
    'scenarios',
    metadata,
    Column('scenario_id', Text, primary_key=True),
    Column('forecast_revision_id', Text,
           ForeignKey('forecast_revisions.forecast_revision_id', ondelete='RESTRICT'),
           nullable=False),
    Column('label', Text, nullable=False),
    Column('probability', Float, nullable=True),
    Column('note', Text, nullable=True),
)
