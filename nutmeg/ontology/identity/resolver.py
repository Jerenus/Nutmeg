"""Read-only, provider-ID-first identity resolution.

Resolution order is strict and auditable: an exact provider external id wins;
failing that, a curated alias; failing that, nothing. The resolver never writes
and never fabricates an id — an unresolved entity is the caller's cue to create a
provisional one (via a typed Action), never to guess by string similarity.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from nutmeg.ontology.identity.models import EntityType
from nutmeg.ontology.repository.identity import IdentityRepository


class ResolutionMethod(StrEnum):
    PROVIDER_ID = 'provider_id'
    ALIAS = 'alias'


@dataclass(frozen=True, slots=True)
class Resolution:
    entity_id: str | None
    method: ResolutionMethod | None


def resolve_entity(
    repository: IdentityRepository,
    entity_type: EntityType,
    *,
    provider: str | None = None,
    external_id: str | None = None,
    aliases: Sequence[str] = (),
) -> Resolution:
    if provider and external_id:
        entity_id = repository.entity_by_external_id(
            entity_type, provider=provider, external_id=external_id
        )
        if entity_id is not None:
            return Resolution(entity_id, ResolutionMethod.PROVIDER_ID)
    for alias in aliases:
        entity_id = repository.entity_by_alias(entity_type, alias)
        if entity_id is not None:
            return Resolution(entity_id, ResolutionMethod.ALIAS)
    return Resolution(None, None)
