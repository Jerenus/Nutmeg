"""Provisional-entity Actions on the Package 1 kernel.

`upsert_team` resolves an incoming team provider-id-first, then by curated alias;
only when nothing matches does it mint a **provisional** team and link its
provider id and canonical alias. Two calls carrying the same provider id resolve
to the same entity — identity is never guessed from name similarity, and never
null. Permission (connector/deterministic_system) is enforced by the kernel
before the handler runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, TeamKind, mint_id
from nutmeg.ontology.identity.resolver import resolve_entity
from nutmeg.ontology.repository.identity import TeamRow


@dataclass(frozen=True, slots=True)
class UpsertTeamRequest:
    canonical_name: str
    team_kind: TeamKind
    country: str | None
    provider: str | None
    external_id: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.canonical_name.strip():
            raise ValueError('canonical_name is required')
        if not self.actor_id.strip():
            raise ValueError('actor_id is required')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class EntityActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def upsert_team(self, request: UpsertTeamRequest) -> ActionOutcome:
        payload: dict[str, object] = {
            'entity_type': EntityType.TEAM.value,
            'canonical_name': request.canonical_name,
            'team_kind': request.team_kind.value,
            'country': request.country,
            'provider': request.provider,
            'external_id': request.external_id,
        }
        command = ActionCommand.create(
            action_type='upsert_provisional_entity',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            resolution = resolve_entity(
                uow.identity,
                EntityType.TEAM,
                provider=request.provider,
                external_id=request.external_id,
                aliases=(request.canonical_name.casefold(),),
            )
            if resolution.entity_id is not None:
                return (ObjectRef('team', resolution.entity_id),)
            team_id = mint_id(EntityType.TEAM)
            uow.identity.insert_team(
                TeamRow(
                    team_id=team_id,
                    team_kind=request.team_kind,
                    canonical_name=request.canonical_name,
                    country=request.country,
                    resolution_status=ResolutionStatus.PROVISIONAL,
                    created_at=request.requested_at.astimezone(UTC).isoformat(),
                )
            )
            if request.provider and request.external_id:
                uow.identity.link_external_identifier(
                    entity_id=team_id,
                    entity_type=EntityType.TEAM,
                    provider=request.provider,
                    external_id=request.external_id,
                )
            uow.identity.add_alias(team_id, EntityType.TEAM, request.canonical_name)
            return (ObjectRef('team', team_id),)

        return self._action_service.execute(command, handler)
