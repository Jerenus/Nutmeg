"""RecordMatch — a Match with a real schedule and exactly two appearances.

The Match id is opaque; the sporttery/足彩 provider id lives in ExternalIdentifier.
`scheduled_at` is stored verbatim as computed by the parser (a real kickoff
instant), or explicitly NULL with `schedule_status='unknown'` — never the
ingestion time. A second call carrying the same provider id resolves to the same
Match instead of creating a duplicate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.identity.models import EntityType, MatchSide, MatchStatus, mint_id
from nutmeg.ontology.repository.identity import MatchRevisionRow, TeamAppearanceRow


@dataclass(frozen=True, slots=True)
class MatchSideRef:
    team_id: str
    side: MatchSide


@dataclass(frozen=True, slots=True)
class RecordMatchRequest:
    provider: str
    external_id: str
    scheduled_at: str | None
    schedule_status: str
    status: MatchStatus
    home: MatchSideRef
    away: MatchSideRef
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    competition_edition_id: str | None = None
    venue_id: str | None = None
    round_label: str | None = None

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if self.scheduled_at is None and self.schedule_status != 'unknown':
            raise ValueError("schedule_status must be 'unknown' when scheduled_at is None")
        if self.home.side is self.away.side:
            raise ValueError('home and away must have distinct sides')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class MatchActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def record_match(self, request: RecordMatchRequest) -> ActionOutcome:
        payload: dict[str, object] = {
            'provider': request.provider,
            'external_id': request.external_id,
            'scheduled_at': request.scheduled_at,
            'schedule_status': request.schedule_status,
            'status': request.status.value,
            'home_team_id': request.home.team_id,
            'away_team_id': request.away.team_id,
        }
        command = ActionCommand.create(
            action_type='record_match',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            existing = uow.identity.entity_by_external_id(
                EntityType.MATCH, provider=request.provider, external_id=request.external_id
            )
            if existing is not None:
                return (ObjectRef('match', existing),)
            match_id = mint_id(EntityType.MATCH)
            recorded_at = request.requested_at.astimezone(UTC).isoformat()
            uow.identity.insert_match(match_id)
            uow.identity.insert_match_revision(
                MatchRevisionRow(
                    match_revision_id=f'mrv-{uuid4().hex}',
                    match_id=match_id,
                    version=1,
                    competition_edition_id=request.competition_edition_id,
                    scheduled_at=request.scheduled_at,
                    schedule_status=request.schedule_status,
                    venue_id=request.venue_id,
                    status=request.status.value,
                    round_label=request.round_label,
                    recorded_at=recorded_at,
                    supersedes_revision_id=None,
                )
            )
            for ref in (request.home, request.away):
                uow.identity.insert_team_appearance(
                    TeamAppearanceRow(
                        team_appearance_id=f'tap-{uuid4().hex}',
                        match_id=match_id,
                        team_id=ref.team_id,
                        side=ref.side.value,
                    )
                )
            uow.identity.link_external_identifier(
                entity_id=match_id,
                entity_type=EntityType.MATCH,
                provider=request.provider,
                external_id=request.external_id,
            )
            return (ObjectRef('match', match_id),)

        return self._action_service.execute(command, handler)
