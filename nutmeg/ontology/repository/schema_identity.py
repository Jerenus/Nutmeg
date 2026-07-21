"""Identity Core tables on the shared ontology MetaData.

Opaque entity ids, provider external ids as a unique lookup, curated aliases,
reversible merges. A standard football Match has exactly two TeamAppearance rows
(one designated home, one designated away) — enforced by the UNIQUE(match_id,
side) constraint plus application checks — avoiding a Match<->TeamAppearance
bidirectional FK cycle.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)

from nutmeg.ontology.repository.schema import metadata

competitions = Table(
    'competitions',
    metadata,
    Column('competition_id', Text, primary_key=True),
    Column('name', Text, nullable=False),
    Column('country', Text, nullable=True),
    Column('kind', Text, nullable=False),
)

competition_editions = Table(
    'competition_editions',
    metadata,
    Column('competition_edition_id', Text, primary_key=True),
    Column(
        'competition_id',
        Text,
        ForeignKey('competitions.competition_id', ondelete='RESTRICT'),
        nullable=False,
    ),
    Column('name', Text, nullable=False),
    Column('country', Text, nullable=True),
    Column('format', Text, nullable=True),
    Column('season_label', Text, nullable=True),
    Column('stage', Text, nullable=True),
    Column('valid_from', Text, nullable=True),
    Column('valid_to', Text, nullable=True),
)

teams = Table(
    'teams',
    metadata,
    Column('team_id', Text, primary_key=True),
    Column('team_kind', Text, nullable=False),
    Column('canonical_name', Text, nullable=False),
    Column('country', Text, nullable=True),
    Column('resolution_status', Text, nullable=False),
    Column('created_at', Text, nullable=False),
)

venues = Table(
    'venues',
    metadata,
    Column('venue_id', Text, primary_key=True),
    Column('canonical_name', Text, nullable=False),
    Column('country', Text, nullable=True),
    Column('latitude', Float, nullable=True),
    Column('longitude', Float, nullable=True),
    Column('timezone', Text, nullable=True),
    Column('resolution_status', Text, nullable=False),
    Column('created_at', Text, nullable=False),
)

matches = Table(
    'matches',
    metadata,
    Column('match_id', Text, primary_key=True),
    Column('current_revision_id', Text, nullable=True),
)

match_revisions = Table(
    'match_revisions',
    metadata,
    Column('match_revision_id', Text, primary_key=True),
    Column('match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'), nullable=False),
    Column('version', Integer, nullable=False),
    Column(
        'competition_edition_id',
        Text,
        ForeignKey('competition_editions.competition_edition_id', ondelete='RESTRICT'),
        nullable=True,
    ),
    Column('scheduled_at', Text, nullable=True),
    Column('schedule_status', Text, nullable=False),
    Column('venue_id', Text, ForeignKey('venues.venue_id', ondelete='RESTRICT'), nullable=True),
    Column('status', Text, nullable=False),
    Column('round_label', Text, nullable=True),
    Column('recorded_at', Text, nullable=False),
    Column('supersedes_revision_id', Text, nullable=True),
    UniqueConstraint('match_id', 'version', name='uq_match_revisions_match_version'),
)

team_appearances = Table(
    'team_appearances',
    metadata,
    Column('team_appearance_id', Text, primary_key=True),
    Column(
        'match_id', Text, ForeignKey('matches.match_id', ondelete='RESTRICT'), nullable=False,
        index=True,
    ),
    Column('team_id', Text, ForeignKey('teams.team_id', ondelete='RESTRICT'), nullable=False),
    Column('side', Text, nullable=False),
    UniqueConstraint('match_id', 'side', name='uq_team_appearances_match_side'),
)

external_identifiers = Table(
    'external_identifiers',
    metadata,
    Column('entity_id', Text, nullable=False, index=True),
    Column('entity_type', Text, nullable=False),
    Column('provider', Text, nullable=False),
    Column('external_id', Text, nullable=False),
    Column('valid_from', Text, nullable=True),
    Column('valid_to', Text, nullable=True),
    PrimaryKeyConstraint('provider', 'entity_type', 'external_id', name='pk_external_identifiers'),
)

entity_aliases = Table(
    'entity_aliases',
    metadata,
    Column('entity_id', Text, nullable=False),
    Column('entity_type', Text, nullable=False),
    Column('normalized_alias', Text, nullable=False),
    Column('language', Text, nullable=True),
    Column('provider', Text, nullable=True),
    PrimaryKeyConstraint(
        'entity_type', 'normalized_alias', 'entity_id', name='pk_entity_aliases'
    ),
)

entity_merges = Table(
    'entity_merges',
    metadata,
    Column('merge_id', Text, primary_key=True),
    Column('from_id', Text, nullable=False, index=True),
    Column('into_id', Text, nullable=False),
    Column('entity_type', Text, nullable=False),
    Column('reason', Text, nullable=False),
    Column('evidence_retrieval_ids_json', Text, nullable=False, server_default=text("'[]'")),
    Column('actor_id', Text, nullable=False),
    Column('at', Text, nullable=False),
    Column('reversible', Integer, nullable=False, server_default=text('1')),
)
