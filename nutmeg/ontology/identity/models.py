"""Identity value objects for the football world.

Entity ids are opaque and prefixed by type (`team-<hex>`, `match-<hex>`), never
derived from team names or dates — string identity is exactly the drift bug
Package 2A removes. Enum values are stable snake_case and are the strings stored
in the database.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4


class EntityType(StrEnum):
    COMPETITION = 'competition'
    COMPETITION_EDITION = 'competition_edition'
    TEAM = 'team'
    VENUE = 'venue'
    PERSON = 'person'
    MATCH = 'match'


class ResolutionStatus(StrEnum):
    PROVISIONAL = 'provisional'
    RESOLVED = 'resolved'
    MERGED = 'merged'
    RETIRED = 'retired'


class TeamKind(StrEnum):
    CLUB = 'club'
    NATIONAL = 'national'
    SELECTION = 'selection'


class MatchSide(StrEnum):
    HOME = 'home'
    AWAY = 'away'
    NEUTRAL_DESIGNATED_HOME = 'neutral_designated_home'
    NEUTRAL_DESIGNATED_AWAY = 'neutral_designated_away'


class MatchStatus(StrEnum):
    SCHEDULED = 'scheduled'
    LIVE = 'live'
    FINISHED = 'finished'
    POSTPONED = 'postponed'
    CANCELLED = 'cancelled'


@dataclass(frozen=True, slots=True)
class CompetitionEditionRef:
    """One exact curated competition edition safe to attach to a Match."""

    competition_id: str
    competition_name: str
    competition_country: str | None
    competition_kind: str
    competition_edition_id: str
    edition_name: str
    season_label: str


def mint_id(entity_type: EntityType) -> str:
    return f'{entity_type.value}-{uuid4().hex}'
