"""Context (people) Core tables on the shared ontology MetaData.

TeamAppearance carries the stable participation; rest/condition/motivation and
availability/lineup are time-and-source-bound context here. Every status/lineup
row can reference a backing Observation (``observation_id``) so "状态≠null" and
every status traces to evidence.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    Table,
    Text,
    text,
)

from nutmeg.ontology.repository.schema import metadata

persons = Table(
    'persons',
    metadata,
    Column('person_id', Text, primary_key=True),
    Column('canonical_name', Text, nullable=False),
    Column('birth_date', Text, nullable=True),
    Column('nationality', Text, nullable=True),
    Column('resolution_status', Text, nullable=False),
    Column('created_at', Text, nullable=False),
)

role_assignments = Table(
    'role_assignments',
    metadata,
    Column('role_assignment_id', Text, primary_key=True),
    Column('person_id', Text, ForeignKey('persons.person_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('team_id', Text, ForeignKey('teams.team_id', ondelete='RESTRICT'), nullable=False),
    Column('role_type', Text, nullable=False),
    Column('position_group', Text, nullable=True),
    Column('valid_from', Text, nullable=False),
    Column('valid_to', Text, nullable=True),
    Column('source_observation_id', Text, nullable=True),
)

person_match_statuses = Table(
    'person_match_statuses',
    metadata,
    Column('person_match_status_id', Text, primary_key=True),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('person_id', Text, ForeignKey('persons.person_id', ondelete='RESTRICT'), nullable=False),
    Column('team_appearance_id', Text,
           ForeignKey('team_appearances.team_appearance_id', ondelete='RESTRICT'), nullable=True),
    Column('availability', Text, nullable=False),
    Column('status_kind', Text, nullable=False),
    Column('valid_from', Text, nullable=False),
    Column('valid_to', Text, nullable=True),
    Column('observation_id', Text, nullable=True),
)

lineup_entries = Table(
    'lineup_entries',
    metadata,
    Column('lineup_entry_id', Text, primary_key=True),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'),
           nullable=False, index=True),
    Column('person_id', Text, ForeignKey('persons.person_id', ondelete='RESTRICT'), nullable=False),
    Column('team_appearance_id', Text,
           ForeignKey('team_appearances.team_appearance_id', ondelete='RESTRICT'), nullable=True),
    Column('lineup_status', Text, nullable=False),
    Column('role', Text, nullable=False),
    Column('position', Text, nullable=True),
    Column('shirt_number', Text, nullable=True),
    Column('captain', Integer, nullable=False, server_default=text('0')),
    Column('observed_at', Text, nullable=False),
    Column('observation_id', Text, nullable=True),
)
