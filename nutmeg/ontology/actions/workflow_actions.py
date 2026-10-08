"""Governed Actions for human adjudication and prediction workflows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.service import ActionBatchItem, ActionService
from nutmeg.ontology.workflow.models import (
    AdjudicationRow,
    PredictionRow,
    PredictionStatus,
    mint_workflow_id,
)

if TYPE_CHECKING:
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _require_aware(requested_at: datetime) -> None:
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError('requested_at must be timezone-aware')


@dataclass(frozen=True, slots=True)
class RecordAdjudicationRequest:
    subject_type: str
    subject_id: str
    decision: str
    reason: str
    evidence_rejected: list[dict[str, str]]
    alternative: dict[str, object]
    supersedes_adjudication_id: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)


def insert_adjudication_in_uow(
    uow: OntologyUnitOfWork,
    request: RecordAdjudicationRequest,
    *,
    adjudication_id: str | None = None,
) -> str:
    """Insert one Adjudication inside an already governed outer Action."""
    resolved_id = adjudication_id or mint_workflow_id('adj')
    uow.workflow.insert_adjudication(
        AdjudicationRow(
            adjudication_id=resolved_id,
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            decision=request.decision,
            actor_id=request.actor_id,
            reason=request.reason,
            evidence_rejected=list(request.evidence_rejected),
            alternative=dict(request.alternative),
            created_at=request.requested_at.astimezone(UTC).isoformat(),
            supersedes_adjudication_id=request.supersedes_adjudication_id,
        )
    )
    return resolved_id


@dataclass(frozen=True, slots=True)
class RegisterPredictionRequest:
    match_id: str | None
    subject_type: str
    subject_id: str
    claim: str
    falsifier: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)
        if self.subject_type not in ('match', 'issue'):
            raise ValueError('subject_type must be match or issue')
        if self.subject_type == 'match' and self.match_id != self.subject_id:
            raise ValueError('match-scoped prediction requires subject_id == match_id')
        if self.subject_type == 'issue' and self.match_id is not None:
            raise ValueError('issue-scoped prediction must not carry match_id')


_GRADE_OUTCOME_STATUS = {
    'hit': PredictionStatus.CONFIRMED,
    'miss': PredictionStatus.REFUTED,
    'na': PredictionStatus.VOID,
}


@dataclass(frozen=True, slots=True)
class GradePredictionRequest:
    prediction_id: str
    outcome: str
    reason: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)
        if self.outcome not in ('hit', 'miss', 'na'):
            raise ValueError('outcome must be hit, miss, or na')
        if not self.reason.strip():
            raise ValueError('grade reason is required')


class WorkflowActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def record_adjudication(
        self, request: RecordAdjudicationRequest
    ) -> ActionOutcome:
        command, handler = self.prepare_record_adjudication(request)
        return self._action_service.execute(command, handler)

    def prepare_record_adjudication(
        self,
        request: RecordAdjudicationRequest,
        *,
        action_id: str | None = None,
    ) -> ActionBatchItem:
        """Build an adjudication operation without opening a transaction."""
        command = ActionCommand.for_request(
            'record_adjudication',
            request,
            {
                'subject_type': request.subject_type,
                'subject_id': request.subject_id,
                'decision': request.decision,
                'reason': request.reason,
                'evidence_rejected': request.evidence_rejected,
                'alternative': request.alternative,
                'supersedes_adjudication_id': request.supersedes_adjudication_id,
            },
            action_id=action_id,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            adjudication_id = insert_adjudication_in_uow(uow, request)
            return (ObjectRef('adjudication', adjudication_id),)

        return command, handler

    def register_prediction(
        self, request: RegisterPredictionRequest
    ) -> ActionOutcome:
        command, handler = self.prepare_register_prediction(request)
        return self._action_service.execute(command, handler)

    def prepare_register_prediction(
        self,
        request: RegisterPredictionRequest,
        *,
        action_id: str | None = None,
    ) -> ActionBatchItem:
        """Build a prediction operation without opening a transaction."""
        command = ActionCommand.for_request(
            'register_prediction',
            request,
            {
                'match_id': request.match_id,
                'subject_type': request.subject_type,
                'subject_id': request.subject_id,
                'claim': request.claim,
                'falsifier': request.falsifier,
            },
            action_id=action_id,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            prediction_id = mint_workflow_id('prediction')
            uow.workflow.insert_prediction(
                PredictionRow(
                    prediction_id=prediction_id,
                    match_id=request.match_id,
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    claim=request.claim,
                    falsifier=request.falsifier,
                    status=PredictionStatus.PENDING,
                    outcome=None,
                    registered_at=self._at(request),
                    settled_at=None,
                )
            )
            return (ObjectRef('prediction', prediction_id),)

        return command, handler

    def grade_prediction(self, request: GradePredictionRequest) -> ActionOutcome:
        command = ActionCommand.for_request(
            'grade_prediction',
            request,
            {
                'prediction_id': request.prediction_id,
                'outcome': request.outcome,
                'reason': request.reason,
            },
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            prediction = uow.workflow.get_prediction(request.prediction_id)
            if (
                prediction.status is not PredictionStatus.PENDING
                or prediction.outcome is not None
            ):
                raise ValueError(
                    f'prediction {request.prediction_id} is already graded'
                )
            uow.workflow.update_prediction_outcome(
                request.prediction_id,
                request.outcome,
                _GRADE_OUTCOME_STATUS[request.outcome].value,
                self._at(request),
            )
            return (ObjectRef('prediction', request.prediction_id),)

        return self._action_service.execute(command, handler)

    @staticmethod
    def _at(request) -> str:
        return request.requested_at.astimezone(UTC).isoformat()
