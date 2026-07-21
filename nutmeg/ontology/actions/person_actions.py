"""Provisional-person Actions on the Package 1 kernel.

Mirrors ``EntityActions.upsert_team``: resolves an incoming person provider-id-first
then by curated alias over the shared external-identifier/alias tables, minting a
provisional person only when nothing matches. Identity is never guessed from a
name string and never null.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import EntityType, ResolutionStatus, mint_id
from nutmeg.ontology.identity.resolver import resolve_entity
from nutmeg.ontology.repository.identity import PersonRow


@dataclass(frozen=True, slots=True)
class UpsertPersonRequest:
    canonical_name: str
    provider: str | None
    external_id: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    birth_date: str | None = None
    nationality: str | None = None

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.canonical_name.strip():
            raise ValueError('canonical_name is required')
        if not self.actor_id.strip():
            raise ValueError('actor_id is required')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class PersonActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def upsert_person(self, request: UpsertPersonRequest) -> ActionOutcome:
        payload: dict[str, object] = {
            'entity_type': EntityType.PERSON.value,
            'canonical_name': request.canonical_name,
            'provider': request.provider,
            'external_id': request.external_id,
        }
        command = ActionCommand.create(
            action_type='upsert_person',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            resolution = resolve_entity(
                uow.identity,
                EntityType.PERSON,
                provider=request.provider,
                external_id=request.external_id,
                aliases=(request.canonical_name.casefold(),),
            )
            if resolution.entity_id is not None:
                return (ObjectRef('person', resolution.entity_id),)
            person_id = mint_id(EntityType.PERSON)
            uow.identity.insert_person(
                PersonRow(
                    person_id=person_id,
                    canonical_name=request.canonical_name,
                    birth_date=request.birth_date,
                    nationality=request.nationality,
                    resolution_status=ResolutionStatus.PROVISIONAL,
                    created_at=request.requested_at.astimezone(UTC).isoformat(),
                )
            )
            if request.provider and request.external_id:
                uow.identity.link_external_identifier(
                    entity_id=person_id,
                    entity_type=EntityType.PERSON,
                    provider=request.provider,
                    external_id=request.external_id,
                )
            uow.identity.add_alias(person_id, EntityType.PERSON, request.canonical_name)
            return (ObjectRef('person', person_id),)

        return self._action_service.execute(command, handler)
