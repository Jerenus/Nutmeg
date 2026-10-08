"""Identity persistence: entities, external ids, aliases, matches.

Provider external ids are a unique lookup keyed by (provider, entity_type,
external_id); the same id may not point at two entities. Aliases are stored and
queried case-folded so curated Chinese/English names resolve regardless of
casing. Nothing here fabricates an id — resolution is provider-id-first, then
alias, then nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select, update

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
class CompetitionRow:
    competition_id: str
    name: str
    country: str | None
    kind: str


@dataclass(frozen=True, slots=True)
class CompetitionEditionRow:
    competition_edition_id: str
    competition_id: str
    name: str
    country: str | None
    format: str | None
    season_label: str | None
    stage: str | None
    valid_from: str | None
    valid_to: str | None


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

    def ensure_competition(self, row: CompetitionRow) -> None:
        existing = self._connection.execute(
            select(si.competitions).where(si.competitions.c.competition_id == row.competition_id)
        ).mappings().first()
        values = {
            "competition_id": row.competition_id,
            "name": row.name,
            "country": row.country,
            "kind": row.kind,
        }
        if existing is None:
            self._connection.execute(insert(si.competitions).values(**values))
        elif dict(existing) != values:
            raise OntologyError(f"competition {row.competition_id} conflicts with curated seed")

    def ensure_competition_edition(self, row: CompetitionEditionRow) -> None:
        existing = self._connection.execute(
            select(si.competition_editions).where(
                si.competition_editions.c.competition_edition_id
                == row.competition_edition_id
            )
        ).mappings().first()
        values = {
            "competition_edition_id": row.competition_edition_id,
            "competition_id": row.competition_id,
            "name": row.name,
            "country": row.country,
            "format": row.format,
            "season_label": row.season_label,
            "stage": row.stage,
            "valid_from": row.valid_from,
            "valid_to": row.valid_to,
        }
        if existing is None:
            self._connection.execute(insert(si.competition_editions).values(**values))
        elif dict(existing) != values:
            raise OntologyError(
                f"competition edition {row.competition_edition_id} conflicts with curated seed"
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

    def insert_match(self, match_id: str) -> None:
        self._connection.execute(
            insert(si.matches).values(match_id=match_id, current_revision_id=None)
        )

    def insert_match_minimal(self, match_id: str) -> None:
        """A bare matches row (no revision) — used to satisfy market FKs in tests/tooling."""
        self.insert_match(match_id)

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

    def count_teams(self) -> int:
        return self._connection.execute(select(func.count()).select_from(si.teams)).scalar_one()

    def count_matches(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(si.matches)
        ).scalar_one()

    def all_match_ids(self) -> tuple[str, ...]:
        rows = self._connection.execute(select(si.matches.c.match_id)).scalars().all()
        return tuple(rows)
