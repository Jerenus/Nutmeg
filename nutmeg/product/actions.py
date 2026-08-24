"""Explicit product Action whitelist over governed ontology services."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from nutmeg.ontology.actions.forecast_actions import FactorInput
from nutmeg.ontology.actions.models import ActionOutcome, ActorRole
from nutmeg.ontology.actions.workflow_actions import (
    CreateAgentProposalRequest,
    LinkPrecedentRequest,
    RecordAdjudicationRequest,
    RecordFlagInstanceRequest,
    RegisterPredictionRequest,
    ResolveAgentProposalRequest,
)
from nutmeg.ontology.decision.read_flow import ReadMatchRequest
from nutmeg.ontology.workflow.models import ProposalStatus
from nutmeg.product.contracts import (
    ObjectRefContract,
    ProductActionRequest,
    ProductActionResponse,
    ReadinessLevel,
)
from nutmeg.product.errors import (
    ProductActionBlockedError,
    ProductActionNotAllowedError,
    ProductNotFoundError,
)
from nutmeg.product.readiness import evaluate_readiness
from nutmeg.product.repository import ProductReadRepository

_ALLOWED_ACTIONS = {
    'commit_forecast',
    'record_adjudication',
    'record_flag_instance',
    'register_prediction',
    'link_precedent',
    'create_agent_proposal',
    'resolve_agent_proposal',
}


class ProductActionGateway:
    def __init__(
        self,
        kernel,
        repository: ProductReadRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._kernel = kernel
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        request: ProductActionRequest,
        *,
        actor_id: str = 'owner',
        actor_role: ActorRole = ActorRole.JUDGE_OPERATOR,
    ) -> ProductActionResponse:
        if request.action_type not in _ALLOWED_ACTIONS:
            raise ProductActionNotAllowedError(
                f'product action {request.action_type} is not allowed'
            )
        if request.policy_version != 'governance-v1':
            raise ProductActionNotAllowedError(
                f'policy version {request.policy_version} is not allowed'
            )
        requested_at = self._clock()
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError('product Action clock must be timezone-aware')

        if request.action_type == 'commit_forecast':
            return self._commit_forecast(request, actor_id, actor_role, requested_at)
        outcome = self._execute_workflow(
            request, actor_id=actor_id, actor_role=actor_role, requested_at=requested_at
        )
        return _response(outcome)

    def _commit_forecast(
        self,
        request: ProductActionRequest,
        actor_id: str,
        actor_role: ActorRole,
        requested_at: datetime,
    ) -> ProductActionResponse:
        payload = request.payload
        match_id = _required_str(payload, 'match_id')
        market_id = _required_str(payload, 'market_definition_id')
        cutoff_text = _required_str(payload, 'cutoff_at')
        cutoff = _parse_aware(cutoff_text, 'cutoff_at')
        version_key = f'forecast:{match_id}:{market_id}'
        if version_key not in request.expected_versions:
            raise ValueError(f'expected version {version_key} is required')

        match = self._repository.match(match_id, cutoff.isoformat())
        if match is None:
            raise ProductNotFoundError(f'match {match_id} not found')
        snapshot = self._repository.latest_snapshot(match_id, market_id, cutoff.isoformat())
        observations = self._repository.observations_for_match(
            match_id, cutoff.isoformat()
        )
        claims = self._repository.claims_for_match(match_id, cutoff.isoformat())
        readiness = evaluate_readiness(
            identity_resolved=(
                match['home_resolution_status'] == 'resolved'
                and match['away_resolution_status'] == 'resolved'
            ),
            snapshot_at=_parse_aware(snapshot['as_of'], 'snapshot.as_of') if snapshot else None,
            as_of=cutoff,
            evidence_count=len(observations) + len(claims),
        )
        if readiness.level is ReadinessLevel.BLOCKED:
            codes = ', '.join(issue.code for issue in readiness.issues)
            raise ProductActionBlockedError(f'forecast is blocked: {codes}')
        assert snapshot is not None

        result = self._kernel.decision_read.read_match(
            ReadMatchRequest(
                match_id=match_id,
                market_definition_id=market_id,
                operator_id=actor_id,
                cutoff_at=cutoff.isoformat(),
                prior_distribution={
                    str(key): float(value)
                    for key, value in snapshot['fair_distribution'].items()
                },
                belief_distribution=_float_distribution(payload, 'belief_distribution'),
                factors=_factors(payload.get('factors', [])),
                actor_id=actor_id,
                actor_role=actor_role,
                requested_at=requested_at,
                commitment_tier=str(payload.get('commitment_tier', 'judged')),
                prior_snapshot_id=snapshot['market_snapshot_id'],
                candidate_observation_ids=[item['observation_id'] for item in observations],
                caveat_claim_ids=[item['claim_id'] for item in claims],
                falsifier=_optional_str(payload.get('falsifier')),
                idempotency_key=request.idempotency_key,
                expected_current_revision_no=request.expected_versions[version_key],
            )
        )
        refs = (
            [
                ObjectRefContract(
                    object_type='forecast_revision', object_id=result.forecast_revision_id
                )
            ]
            if result.forecast_revision_id is not None
            else []
        )
        return ProductActionResponse(
            action_id=result.forecast_action_id,
            action_type='commit_forecast',
            status='committed' if result.committed else 'rejected',
            result_refs=refs,
        )

    def _execute_workflow(
        self,
        request: ProductActionRequest,
        *,
        actor_id: str,
        actor_role: ActorRole,
        requested_at: datetime,
    ) -> ActionOutcome:
        payload = request.payload
        common = {
            'actor_id': actor_id,
            'actor_role': actor_role,
            'idempotency_key': request.idempotency_key,
            'requested_at': requested_at,
        }
        if request.action_type == 'record_adjudication':
            return self._kernel.workflow.record_adjudication(
                RecordAdjudicationRequest(
                    subject_type=_required_str(payload, 'subject_type'),
                    subject_id=_required_str(payload, 'subject_id'),
                    decision=_required_str(payload, 'decision'),
                    reason=_required_str(payload, 'reason'),
                    evidence_rejected=_reference_list(payload.get('evidence_rejected', [])),
                    alternative=_object_dict(payload.get('alternative', {}), 'alternative'),
                    supersedes_adjudication_id=_optional_str(
                        payload.get('supersedes_adjudication_id')
                    ),
                    **common,
                )
            )
        if request.action_type == 'record_flag_instance':
            return self._kernel.workflow.record_flag_instance(
                RecordFlagInstanceRequest(
                    flag_type=_required_str(payload, 'flag_type'),
                    match_id=_required_str(payload, 'match_id'),
                    direction=_optional_str(payload.get('direction')),
                    strength=float(payload.get('strength', 0.0)),
                    evidence_refs=_reference_list(payload.get('evidence_refs', [])),
                    predicted_face=_optional_str(payload.get('predicted_face')),
                    status=str(payload.get('status', 'active')),
                    **common,
                )
            )
        if request.action_type == 'register_prediction':
            return self._kernel.workflow.register_prediction(
                RegisterPredictionRequest(
                    match_id=_required_str(payload, 'match_id'),
                    claim=_required_str(payload, 'claim'),
                    falsifier=_required_str(payload, 'falsifier'),
                    **common,
                )
            )
        if request.action_type == 'link_precedent':
            return self._kernel.workflow.link_precedent(
                LinkPrecedentRequest(
                    subject_type=_required_str(payload, 'subject_type'),
                    subject_id=_required_str(payload, 'subject_id'),
                    precedent_match_id=_required_str(payload, 'precedent_match_id'),
                    scope=_required_str(payload, 'scope'),
                    evidence_refs=_reference_list(payload.get('evidence_refs', [])),
                    **common,
                )
            )
        if request.action_type == 'create_agent_proposal':
            return self._kernel.workflow.create_agent_proposal(
                CreateAgentProposalRequest(
                    subject_type=_required_str(payload, 'subject_type'),
                    subject_id=_required_str(payload, 'subject_id'),
                    proposal_type=_required_str(payload, 'proposal_type'),
                    payload=_object_dict(payload.get('payload', {}), 'payload'),
                    citation_refs=_reference_list(payload.get('citation_refs', [])),
                    model_name=_required_str(payload, 'model_name'),
                    model_version=_required_str(payload, 'model_version'),
                    **common,
                )
            )
        proposal_id = _required_str(payload, 'agent_proposal_id')
        version_key = f'agent_proposal:{proposal_id}'
        if version_key not in request.expected_versions:
            raise ValueError(f'expected version {version_key} is required')
        return self._kernel.workflow.resolve_agent_proposal(
            ResolveAgentProposalRequest(
                agent_proposal_id=proposal_id,
                resolution=ProposalStatus(_required_str(payload, 'resolution')),
                expected_version=request.expected_versions[version_key],
                **common,
            )
        )


def _response(outcome: ActionOutcome) -> ProductActionResponse:
    return ProductActionResponse(
        action_id=outcome.action_id,
        action_type=outcome.action_type,
        status=outcome.status.value,
        result_refs=[ObjectRefContract(**ref.to_dict()) for ref in outcome.result_refs],
        error_code=outcome.error_code,
        error_detail=outcome.error_detail,
        committed_at=outcome.committed_at,
    )


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key} is required')
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('optional text value must be a string')
    return value


def _object_dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f'{name} must be an object')
    return {str(key): item for key, item in value.items()}


def _reference_list(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError('references must be a list')
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('each reference must be an object')
        object_type = item.get('object_type')
        object_id = item.get('object_id')
        if not isinstance(object_type, str) or not isinstance(object_id, str):
            raise ValueError('each reference requires object_type and object_id')
        result.append({'object_type': object_type, 'object_id': object_id})
    return result


def _float_distribution(payload: dict[str, object], key: str) -> dict[str, float]:
    value = _object_dict(payload.get(key), key)
    return {name: float(probability) for name, probability in value.items()}


def _factors(value: object) -> list[FactorInput]:
    if not isinstance(value, list):
        raise ValueError('factors must be a list')
    factors: list[FactorInput] = []
    for raw in value:
        item = _object_dict(raw, 'factor')
        factors.append(
            FactorInput(
                factor_definition_id=_required_str(item, 'factor_definition_id'),
                delta=_float_distribution(item, 'delta'),
                scope_entity_ids=_string_list(item.get('scope_entity_ids', [])),
                supporting_observation_ids=_string_list(
                    item.get('supporting_observation_ids', [])
                ),
                note=_optional_str(item.get('note')),
            )
        )
    return factors


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError('value must be a list of strings')
    return list(value)


def _parse_aware(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError(f'{name} must be an ISO timestamp') from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f'{name} must be timezone-aware')
    return parsed.astimezone(UTC)
