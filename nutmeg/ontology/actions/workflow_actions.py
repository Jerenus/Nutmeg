"""Governed Actions for human adjudication and AI proposal workflows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.service import ActionBatchItem, ActionService
from nutmeg.ontology.workflow.models import (
    AdjudicationRow,
    AgentProposalRow,
    FlagInstanceRow,
    PrecedentLinkRow,
    PredictionRow,
    PredictionStatus,
    ProposalStatus,
    mint_workflow_id,
)


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


@dataclass(frozen=True, slots=True)
class RecordFlagInstanceRequest:
    flag_type: str
    match_id: str
    direction: str | None
    strength: float
    evidence_refs: list[dict[str, str]]
    predicted_face: str | None
    status: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)


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


@dataclass(frozen=True, slots=True)
class LinkPrecedentRequest:
    subject_type: str
    subject_id: str
    precedent_match_id: str
    scope: str
    evidence_refs: list[dict[str, str]]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)


@dataclass(frozen=True, slots=True)
class CreateAgentProposalRequest:
    subject_type: str
    subject_id: str
    proposal_type: str
    information_cutoff_at: str
    operator_prompt: str
    payload: dict[str, object]
    citation_refs: list[dict[str, str]]
    model_name: str
    model_version: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)


@dataclass(frozen=True, slots=True)
class ResolveAgentProposalRequest:
    agent_proposal_id: str
    resolution: ProposalStatus
    expected_version: int
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at)
        if self.resolution is ProposalStatus.PENDING:
            raise ValueError('proposal resolution cannot be pending')


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
        command = self._command(
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
            adjudication_id = mint_workflow_id('adj')
            uow.workflow.insert_adjudication(
                AdjudicationRow(
                    adjudication_id=adjudication_id,
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    decision=request.decision,
                    actor_id=request.actor_id,
                    reason=request.reason,
                    evidence_rejected=list(request.evidence_rejected),
                    alternative=dict(request.alternative),
                    created_at=self._at(request),
                    supersedes_adjudication_id=request.supersedes_adjudication_id,
                )
            )
            return (ObjectRef('adjudication', adjudication_id),)

        return command, handler

    def record_flag_instance(
        self, request: RecordFlagInstanceRequest
    ) -> ActionOutcome:
        command = self._command(
            'record_flag_instance',
            request,
            {
                'flag_type': request.flag_type,
                'match_id': request.match_id,
                'direction': request.direction,
                'strength': request.strength,
                'evidence_refs': request.evidence_refs,
                'predicted_face': request.predicted_face,
                'status': request.status,
            },
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            flag_instance_id = mint_workflow_id('flag')
            uow.workflow.insert_flag_instance(
                FlagInstanceRow(
                    flag_instance_id=flag_instance_id,
                    flag_type=request.flag_type,
                    match_id=request.match_id,
                    direction=request.direction,
                    strength=request.strength,
                    evidence_refs=list(request.evidence_refs),
                    predicted_face=request.predicted_face,
                    status=request.status,
                    created_at=self._at(request),
                )
            )
            return (ObjectRef('flag_instance', flag_instance_id),)

        return self._action_service.execute(command, handler)

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
        command = self._command(
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
        command = self._command(
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

    def link_precedent(self, request: LinkPrecedentRequest) -> ActionOutcome:
        command = self._command(
            'link_precedent',
            request,
            {
                'subject_type': request.subject_type,
                'subject_id': request.subject_id,
                'precedent_match_id': request.precedent_match_id,
                'scope': request.scope,
                'evidence_refs': request.evidence_refs,
            },
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            precedent_link_id = mint_workflow_id('precedent')
            uow.workflow.insert_precedent_link(
                PrecedentLinkRow(
                    precedent_link_id=precedent_link_id,
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    precedent_match_id=request.precedent_match_id,
                    scope=request.scope,
                    evidence_refs=list(request.evidence_refs),
                    created_at=self._at(request),
                )
            )
            return (ObjectRef('precedent_link', precedent_link_id),)

        return self._action_service.execute(command, handler)

    def create_agent_proposal(
        self, request: CreateAgentProposalRequest
    ) -> ActionOutcome:
        command = self._command(
            'create_agent_proposal',
            request,
            {
                'subject_type': request.subject_type,
                'subject_id': request.subject_id,
                'proposal_type': request.proposal_type,
                'information_cutoff_at': request.information_cutoff_at,
                'operator_prompt': request.operator_prompt,
                'payload': request.payload,
                'citation_refs': request.citation_refs,
                'model_name': request.model_name,
                'model_version': request.model_version,
            },
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            if not request.operator_prompt.strip():
                raise ValueError('operator_prompt is required')
            uow.workflow.validate_citation_refs(
                request.subject_type,
                request.subject_id,
                request.citation_refs,
                request.information_cutoff_at,
            )
            proposal_id = mint_workflow_id('proposal')
            uow.workflow.insert_agent_proposal(
                AgentProposalRow(
                    agent_proposal_id=proposal_id,
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    proposal_type=request.proposal_type,
                    information_cutoff_at=request.information_cutoff_at,
                    operator_prompt=request.operator_prompt,
                    payload=dict(request.payload),
                    citation_refs=list(request.citation_refs),
                    model_name=request.model_name,
                    model_version=request.model_version,
                    status=ProposalStatus.PENDING,
                    version=1,
                    created_at=self._at(request),
                    resolved_at=None,
                    resolved_by_action_id=None,
                )
            )
            return (ObjectRef('agent_proposal', proposal_id),)

        return self._action_service.execute(command, handler)

    def resolve_agent_proposal(
        self, request: ResolveAgentProposalRequest
    ) -> ActionOutcome:
        command = self._command(
            'resolve_agent_proposal',
            request,
            {
                'agent_proposal_id': request.agent_proposal_id,
                'resolution': request.resolution.value,
            },
            expected_versions={
                f'agent_proposal:{request.agent_proposal_id}': request.expected_version
            },
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            proposal = uow.workflow.get_agent_proposal(request.agent_proposal_id)
            uow.workflow.validate_citation_refs(
                proposal.subject_type,
                proposal.subject_id,
                proposal.citation_refs,
                proposal.information_cutoff_at,
            )
            uow.workflow.resolve_agent_proposal(
                request.agent_proposal_id,
                request.resolution,
                request.expected_version,
                self._at(request),
                _command.action_id,
            )
            return (ObjectRef('agent_proposal', request.agent_proposal_id),)

        return self._action_service.execute(command, handler)

    @staticmethod
    def _at(request) -> str:
        return request.requested_at.astimezone(UTC).isoformat()

    @staticmethod
    def _command(
        action_type: str,
        request,
        payload: dict[str, object],
        *,
        expected_versions: dict[str, int] | None = None,
        action_id: str | None = None,
    ) -> ActionCommand:
        return ActionCommand.create(
            action_type=action_type,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.requested_at,
            expected_versions=expected_versions,
            action_id=action_id,
        )
