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
from nutmeg.ontology.errors import OntologyError
from nutmeg.ontology.identity.models import (
    CompetitionEditionRef,
    EntityType,
    MatchSide,
    MatchStatus,
    mint_id,
)
from nutmeg.ontology.repository.identity import (
    CompetitionEditionRow,
    CompetitionRow,
    MatchRevisionRow,
    TeamAppearanceRow,
)


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
    competition_edition: CompetitionEditionRef | None = None
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
        if (
            self.competition_edition_id is not None
            and self.competition_edition is not None
            and self.competition_edition_id
            != self.competition_edition.competition_edition_id
        ):
            raise ValueError('competition edition id conflicts with its curated reference')

    @property
    def resolved_competition_edition_id(self) -> str | None:
        if self.competition_edition is not None:
            return self.competition_edition.competition_edition_id
        return self.competition_edition_id


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
            'competition_edition_id': request.resolved_competition_edition_id,
        }
        command = ActionCommand.create(
            action_type='record_match',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def result_refs(match_id: str, match_revision_id: str) -> tuple[ObjectRef, ...]:
            refs = [
                ObjectRef('match', match_id),
                ObjectRef('match_revision', match_revision_id),
            ]
            if request.competition_edition is not None:
                refs.extend(
                    (
                        ObjectRef('competition', request.competition_edition.competition_id),
                        ObjectRef(
                            'competition_edition',
                            request.competition_edition.competition_edition_id,
                        ),
                    )
                )
            return tuple(refs)

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            if request.competition_edition is not None:
                edition = request.competition_edition
                uow.identity.ensure_competition(
                    CompetitionRow(
                        competition_id=edition.competition_id,
                        name=edition.competition_name,
                        country=edition.competition_country,
                        kind=edition.competition_kind,
                    )
                )
                uow.identity.ensure_competition_edition(
                    CompetitionEditionRow(
                        competition_edition_id=edition.competition_edition_id,
                        competition_id=edition.competition_id,
                        name=edition.edition_name,
                        country=edition.competition_country,
                        format=None,
                        season_label=edition.season_label,
                        stage=None,
                        valid_from=None,
                        valid_to=None,
                    )
                )
            existing = uow.identity.entity_by_external_id(
                EntityType.MATCH, provider=request.provider, external_id=request.external_id
            )
            if existing is not None:
                current = uow.identity.current_match_revision(existing)
                edition_id = request.resolved_competition_edition_id
                if current.competition_edition_id is None and edition_id is not None:
                    match_revision_id = f'mrv-{uuid4().hex}'
                    uow.identity.insert_match_revision(
                        MatchRevisionRow(
                            match_revision_id=match_revision_id,
                            match_id=existing,
                            version=current.version + 1,
                            competition_edition_id=edition_id,
                            scheduled_at=current.scheduled_at,
                            schedule_status=current.schedule_status,
                            venue_id=current.venue_id,
                            status=current.status,
                            round_label=current.round_label,
                            recorded_at=request.requested_at.astimezone(UTC).isoformat(),
                            supersedes_revision_id=current.match_revision_id,
                        )
                    )
                    current = uow.identity.current_match_revision(existing)
                elif (
                    edition_id is not None
                    and current.competition_edition_id != edition_id
                ):
                    raise OntologyError(
                        f'match {existing} already belongs to a different competition edition'
                    )
                return result_refs(existing, current.match_revision_id)
            match_id = mint_id(EntityType.MATCH)
            recorded_at = request.requested_at.astimezone(UTC).isoformat()
            uow.identity.insert_match(match_id)
            match_revision_id = f'mrv-{uuid4().hex}'
            uow.identity.insert_match_revision(
                MatchRevisionRow(
                    match_revision_id=match_revision_id,
                    match_id=match_id,
                    version=1,
                    competition_edition_id=request.resolved_competition_edition_id,
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
            return result_refs(match_id, match_revision_id)

        return self._action_service.execute(command, handler)
