"""Evidence Core: ``observations`` on the shared ontology MetaData.

Observations are typed, verification-graded facts scoped to a match. The claim /
claim-span / observation-source tables that once surrounded them were retired in the
2026-10-13 baseline (never populated).
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Table, Text

from nutmeg.ontology.repository.schema import metadata

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

