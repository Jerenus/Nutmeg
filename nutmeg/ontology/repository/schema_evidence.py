"""Evidence Core tables on the shared ontology MetaData.

Claims are immutable source assertions with evidence spans; their ``status`` is a
current projection and every transition appends a ``claim_status_events`` row so
the adjudication trail is replayable. Observations are typed, verification-graded
facts that trace to ArtifactRetrievals. Conflicting claims coexist — nothing here
auto-overwrites.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    ForeignKey,
    PrimaryKeyConstraint,
    Table,
    Text,
)

from nutmeg.ontology.repository.schema import metadata

claims = Table(
    'claims',
    metadata,
    Column('claim_id', Text, primary_key=True),
    Column('subject_type', Text, nullable=False),
    Column('subject_id', Text, nullable=False),
    Column('predicate', Text, nullable=False),
    Column('value_json', Text, nullable=False),
    Column('scope_match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'),
           nullable=True),
    Column('valid_from', Text, nullable=False),
    Column('valid_to', Text, nullable=True),
    Column('status', Text, nullable=False),
    Column('extractor', Text, nullable=False),
    Column('extractor_version', Text, nullable=False),
    Column('created_at', Text, nullable=False),
    Column('adjudicated_at', Text, nullable=True),
)

claim_status_events = Table(
    'claim_status_events',
    metadata,
    Column('claim_status_event_id', Text, primary_key=True),
    Column('claim_id', Text, ForeignKey('claims.claim_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('from_status', Text, nullable=True),
    Column('to_status', Text, nullable=False),
    Column('action_id', Text, nullable=False),
    Column('at', Text, nullable=False),
)

claim_evidence_spans = Table(
    'claim_evidence_spans',
    metadata,
    Column('claim_evidence_span_id', Text, primary_key=True),
    Column('claim_id', Text, ForeignKey('claims.claim_id', ondelete='RESTRICT'), nullable=False),
    Column('artifact_id', Text, ForeignKey('source_artifacts.artifact_id', ondelete='RESTRICT'),
           nullable=False),
    Column('artifact_retrieval_id', Text,
           ForeignKey('artifact_retrievals.artifact_retrieval_id', ondelete='RESTRICT'),
           nullable=False),
    Column('quote', Text, nullable=False),
    Column('locator', Text, nullable=True),
)

observations = Table(
    'observations',
    metadata,
    Column('observation_id', Text, primary_key=True),
    Column('observation_type', Text, nullable=False),
    Column('subject_type', Text, nullable=False),
    Column('subject_id', Text, nullable=False),
    Column('scope_match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'),
           nullable=True),
    Column('value_json', Text, nullable=False),
    Column('schema_version', Text, nullable=False),
    Column('valid_from', Text, nullable=False),
    Column('valid_to', Text, nullable=True),
    Column('observed_at', Text, nullable=False),
    Column('recorded_at', Text, nullable=False),
    Column('verification_method', Text, nullable=False),
    Column('quality_json', Text, nullable=False),
)

observation_sources = Table(
    'observation_sources',
    metadata,
    Column('observation_id', Text, ForeignKey('observations.observation_id', ondelete='RESTRICT'),
           nullable=False),
    Column('artifact_retrieval_id', Text,
           ForeignKey('artifact_retrievals.artifact_retrieval_id', ondelete='RESTRICT'),
           nullable=False),
    PrimaryKeyConstraint('observation_id', 'artifact_retrieval_id', name='pk_observation_sources'),
)

observation_claims = Table(
    'observation_claims',
    metadata,
    Column('observation_id', Text, ForeignKey('observations.observation_id', ondelete='RESTRICT'),
           nullable=False),
    Column('claim_id', Text, ForeignKey('claims.claim_id', ondelete='RESTRICT'), nullable=False),
    PrimaryKeyConstraint('observation_id', 'claim_id', name='pk_observation_claims'),
)
