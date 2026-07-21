"""Context persistence: role assignments, person match statuses, lineup entries.

Each status/lineup row may carry an ``observation_id`` back to the deterministic
Observation that produced it, so "状态≠null" and every status is traceable.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.repository import schema_context as sc


@dataclass(frozen=True, slots=True)
class RoleAssignmentRow:
    role_assignment_id: str
    person_id: str
    team_id: str
    role_type: str
    position_group: str | None
    valid_from: str
    valid_to: str | None
    source_observation_id: str | None


@dataclass(frozen=True, slots=True)
class PersonMatchStatusRow:
    person_match_status_id: str
    match_id: str
    person_id: str
    team_appearance_id: str | None
    availability: str
    status_kind: str
    valid_from: str
    valid_to: str | None
    observation_id: str | None


@dataclass(frozen=True, slots=True)
class LineupEntryRow:
    lineup_entry_id: str
    match_id: str
    person_id: str
    team_appearance_id: str | None
    lineup_status: str
    role: str
    position: str | None
    shirt_number: str | None
    captain: bool
    observed_at: str
    observation_id: str | None


class ContextRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_role_assignment(self, row: RoleAssignmentRow) -> None:
        self._connection.execute(
            insert(sc.role_assignments).values(
                role_assignment_id=row.role_assignment_id,
                person_id=row.person_id,
                team_id=row.team_id,
                role_type=row.role_type,
                position_group=row.position_group,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                source_observation_id=row.source_observation_id,
            )
        )

    def insert_person_match_status(self, row: PersonMatchStatusRow) -> None:
        self._connection.execute(
            insert(sc.person_match_statuses).values(
                person_match_status_id=row.person_match_status_id,
                match_id=row.match_id,
                person_id=row.person_id,
                team_appearance_id=row.team_appearance_id,
                availability=row.availability,
                status_kind=row.status_kind,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                observation_id=row.observation_id,
            )
        )

    def insert_lineup_entry(self, row: LineupEntryRow) -> None:
        self._connection.execute(
            insert(sc.lineup_entries).values(
                lineup_entry_id=row.lineup_entry_id,
                match_id=row.match_id,
                person_id=row.person_id,
                team_appearance_id=row.team_appearance_id,
                lineup_status=row.lineup_status,
                role=row.role,
                position=row.position,
                shirt_number=row.shirt_number,
                captain=1 if row.captain else 0,
                observed_at=row.observed_at,
                observation_id=row.observation_id,
            )
        )

    def person_match_status_ids(self, match_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(sc.person_match_statuses.c.person_match_status_id).where(
                sc.person_match_statuses.c.match_id == match_id
            )
        ).scalars().all()
        return tuple(rows)

    def count_person_match_statuses(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sc.person_match_statuses)
        ).scalar_one()

    def count_lineup_entries(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sc.lineup_entries)
        ).scalar_one()
