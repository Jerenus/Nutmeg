"""Identity persistence: entities, external ids, aliases, merges, matches.

Provider external ids are a unique lookup keyed by (provider, entity_type,
external_id); the same id may not point at two entities. Aliases are stored and
queried case-folded so curated Chinese/English names resolve regardless of
casing. Nothing here fabricates an id — resolution is provider-id-first, then
alias, then nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, insert, select

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
