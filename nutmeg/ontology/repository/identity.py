"""Identity persistence: entities, external ids, aliases, merges, matches.

Provider external ids are a unique lookup keyed by (provider, entity_type,
external_id); the same id may not point at two entities. Aliases are stored and
queried case-folded so curated Chinese/English names resolve regardless of
casing. Nothing here fabricates an id — resolution is provider-id-first, then
alias, then nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import Connection, insert, select, update

from nutmeg.ontology.errors import OntologyError
from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind
from nutmeg.ontology.repository import schema_identity as si


@dataclass(frozen=True, slots=True)
class TeamRow:
    team_id: str
    team_kind: TeamKind
    canonical_name: str
    country: str | None
    resolution_status: ResolutionStatus
    created_at: str


@dataclass(frozen=True, slots=True)
class MatchRevisionRow:
    match_revision_id: str
    match_id: str
    version: int
    competition_edition_id: str | None
    scheduled_at: str | None
    schedule_status: str
    venue_id: str | None
    status: str
    round_label: str | None
    recorded_at: str
    supersedes_revision_id: str | None


@dataclass(frozen=True, slots=True)
class TeamAppearanceRow:
    team_appearance_id: str
    match_id: str
    team_id: str
    side: str


class IdentityRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def insert_team(self, row: TeamRow) -> None:
        self._connection.execute(
            insert(si.teams).values(
                team_id=row.team_id,
                team_kind=row.team_kind.value,
                canonical_name=row.canonical_name,
                country=row.country,
                resolution_status=row.resolution_status.value,
                created_at=row.created_at,
            )
        )

    def link_external_identifier(
        self,
        *,
        entity_id: str,
        entity_type: EntityType,
        provider: str,
        external_id: str,
        valid_from: str | None = None,
    ) -> None:
        existing = self._connection.execute(
            select(si.external_identifiers.c.entity_id).where(
                si.external_identifiers.c.provider == provider,
                si.external_identifiers.c.entity_type == entity_type.value,
                si.external_identifiers.c.external_id == external_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing != entity_id:
                raise OntologyError(
                    f'external id {provider}:{external_id} already maps to {existing}, '
                    f'not {entity_id}'
                )
            return
        self._connection.execute(
            insert(si.external_identifiers).values(
                entity_id=entity_id,
                entity_type=entity_type.value,
                provider=provider,
                external_id=external_id,
                valid_from=valid_from,
                valid_to=None,
            )
        )

    def add_alias(
        self,
        entity_id: str,
        entity_type: EntityType,
        normalized_alias: str,
        *,
        provider: str | None = None,
        language: str | None = None,
    ) -> None:
        alias = normalized_alias.strip().casefold()
        exists = self._connection.execute(
            select(si.entity_aliases.c.entity_id).where(
                si.entity_aliases.c.entity_type == entity_type.value,
                si.entity_aliases.c.normalized_alias == alias,
                si.entity_aliases.c.entity_id == entity_id,
            )
        ).first()
        if exists is not None:
            return
        self._connection.execute(
            insert(si.entity_aliases).values(
                entity_id=entity_id,
                entity_type=entity_type.value,
                normalized_alias=alias,
                language=language,
                provider=provider,
            )
        )

    def entity_by_external_id(
        self,
        entity_type: EntityType,
        *,
        provider: str,
        external_id: str,
    ) -> str | None:
        return self._connection.execute(
            select(si.external_identifiers.c.entity_id).where(
                si.external_identifiers.c.provider == provider,
                si.external_identifiers.c.entity_type == entity_type.value,
                si.external_identifiers.c.external_id == external_id,
            )
        ).scalar_one_or_none()

    def entity_by_alias(self, entity_type: EntityType, normalized_alias: str) -> str | None:
        alias = normalized_alias.strip().casefold()
        return self._connection.execute(
            select(si.entity_aliases.c.entity_id)
            .where(
                si.entity_aliases.c.entity_type == entity_type.value,
                si.entity_aliases.c.normalized_alias == alias,
            )
            .limit(1)
        ).scalar_one_or_none()

    def get_team(self, team_id: str) -> TeamRow:
        row = (
            self._connection.execute(select(si.teams).where(si.teams.c.team_id == team_id))
            .mappings()
            .first()
        )
        if row is None:
            raise OntologyError(f'team {team_id} not found')
        return TeamRow(
            team_id=row['team_id'],
            team_kind=TeamKind(row['team_kind']),
            canonical_name=row['canonical_name'],
            country=row['country'],
            resolution_status=ResolutionStatus(row['resolution_status']),
            created_at=row['created_at'],
        )

    def mark_resolution_status(
        self,
        entity_id: str,
        entity_type: EntityType,
        status: ResolutionStatus,
    ) -> None:
        if entity_type is not EntityType.TEAM:
            raise OntologyError(f'resolution status update not supported for {entity_type.value}')
        self._connection.execute(
            update(si.teams)
            .where(si.teams.c.team_id == entity_id)
            .values(resolution_status=status.value)
        )

    def record_merge(
        self,
        *,
        from_id: str,
        into_id: str,
        entity_type: EntityType,
        reason: str,
        evidence_retrieval_ids: tuple[str, ...] = (),
        actor_id: str,
        at: str,
        reversible: bool = True,
    ) -> None:
        self._connection.execute(
            insert(si.entity_merges).values(
                merge_id=f'merge-{uuid4().hex}',
                from_id=from_id,
                into_id=into_id,
                entity_type=entity_type.value,
                reason=reason,
                evidence_retrieval_ids_json=json.dumps(
                    list(evidence_retrieval_ids), separators=(',', ':')
                ),
                actor_id=actor_id,
                at=at,
                reversible=1 if reversible else 0,
            )
        )
        self.mark_resolution_status(from_id, entity_type, ResolutionStatus.MERGED)

    def redirect(self, entity_id: str, entity_type: EntityType) -> str:
        current = entity_id
        seen = {current}
        while True:
            into = self._connection.execute(
                select(si.entity_merges.c.into_id)
                .where(
                    si.entity_merges.c.from_id == current,
                    si.entity_merges.c.entity_type == entity_type.value,
                )
                .limit(1)
            ).scalar_one_or_none()
            if into is None or into in seen:
                return current
            seen.add(into)
            current = into

    def insert_match(self, match_id: str) -> None:
        self._connection.execute(
            insert(si.matches).values(match_id=match_id, current_revision_id=None)
        )

    def insert_match_revision(self, row: MatchRevisionRow) -> None:
        self._connection.execute(
            insert(si.match_revisions).values(
                match_revision_id=row.match_revision_id,
                match_id=row.match_id,
                version=row.version,
                competition_edition_id=row.competition_edition_id,
                scheduled_at=row.scheduled_at,
                schedule_status=row.schedule_status,
                venue_id=row.venue_id,
                status=row.status,
                round_label=row.round_label,
                recorded_at=row.recorded_at,
                supersedes_revision_id=row.supersedes_revision_id,
            )
        )
        self._connection.execute(
            update(si.matches)
            .where(si.matches.c.match_id == row.match_id)
            .values(current_revision_id=row.match_revision_id)
        )

    def insert_team_appearance(self, row: TeamAppearanceRow) -> None:
        self._connection.execute(
            insert(si.team_appearances).values(
                team_appearance_id=row.team_appearance_id,
                match_id=row.match_id,
                team_id=row.team_id,
                side=row.side,
            )
        )

    def current_match_revision(self, match_id: str) -> MatchRevisionRow:
        current_id = self._connection.execute(
            select(si.matches.c.current_revision_id).where(si.matches.c.match_id == match_id)
        ).scalar_one_or_none()
        if current_id is None:
            raise OntologyError(f'match {match_id} has no current revision')
        row = (
            self._connection.execute(
                select(si.match_revisions).where(
                    si.match_revisions.c.match_revision_id == current_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise OntologyError(f'match revision {current_id} not found')
        return MatchRevisionRow(
            match_revision_id=row['match_revision_id'],
            match_id=row['match_id'],
            version=row['version'],
            competition_edition_id=row['competition_edition_id'],
            scheduled_at=row['scheduled_at'],
            schedule_status=row['schedule_status'],
            venue_id=row['venue_id'],
            status=row['status'],
            round_label=row['round_label'],
            recorded_at=row['recorded_at'],
            supersedes_revision_id=row['supersedes_revision_id'],
        )

    def appearance_sides(self, match_id: str) -> dict[str, str]:
        rows = self._connection.execute(
            select(si.team_appearances.c.side, si.team_appearances.c.team_id).where(
                si.team_appearances.c.match_id == match_id
            )
        ).all()
        return {side: team_id for side, team_id in rows}
