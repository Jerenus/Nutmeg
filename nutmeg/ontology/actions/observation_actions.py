"""RecordObservation — deterministic/official typed facts.

Observations are the connector/deterministic-system write path: official
structured fields (weather, availability, form) become typed Observations that
trace to their ArtifactRetrievals. An AI extractor is rejected here — it can only
propose provisional Claims, never a verified fact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import VerificationMethod, mint_evidence_id
from nutmeg.ontology.repository.evidence import ObservationRow


@dataclass(frozen=True, slots=True)
class RecordObservationRequest:
    observation_type: str
    subject_type: str
    subject_id: str
    scope_match_id: str | None
    value: dict[str, object]
    verification_method: VerificationMethod
    valid_from: str
    observed_at: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    valid_to: str | None = None
    schema_version: str = '1'
    quality: dict[str, object] = field(default_factory=dict)
    artifact_retrieval_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.observation_type.strip() or not self.subject_id.strip():
            raise ValueError('observation_type and subject_id are required')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class ObservationActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def record_observation(self, request: RecordObservationRequest) -> ActionOutcome:
        payload: dict[str, object] = {
            'observation_type': request.observation_type,
            'subject_type': request.subject_type,
            'subject_id': request.subject_id,
            'scope_match_id': request.scope_match_id,
            'verification_method': request.verification_method.value,
            'valid_from': request.valid_from,
            'observed_at': request.observed_at,
        }
        command = ActionCommand.create(
            action_type='record_observation',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            observation_id = self._insert_observation(uow, request)
            return (ObjectRef('observation', observation_id),)

        return self._action_service.execute(command, handler)

    @staticmethod
    def _insert_observation(uow, request: RecordObservationRequest) -> str:
        observation_id = mint_evidence_id('obs')
        uow.evidence.insert_observation(
            ObservationRow(
                observation_id=observation_id,
                observation_type=request.observation_type,
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                scope_match_id=request.scope_match_id,
                value=request.value,
                schema_version=request.schema_version,
                valid_from=request.valid_from,
                valid_to=request.valid_to,
                observed_at=request.observed_at,
                recorded_at=request.requested_at.astimezone(UTC).isoformat(),
                verification_method=request.verification_method.value,
                quality=request.quality,
            ),
            artifact_retrieval_ids=request.artifact_retrieval_ids,
        )
        return observation_id
