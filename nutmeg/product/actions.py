"""Explicit product Action whitelist over governed ontology services."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from nutmeg.ontology.actions.claim_actions import ClaimAdjudicationRequest
from nutmeg.ontology.actions.entity_actions import MergeEntityRequest
from nutmeg.ontology.actions.factor_actions import ApplyFactorStatusRequest
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, FactorInput
from nutmeg.ontology.actions.models import ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.reliability_actions import ApproveReleaseRequest
from nutmeg.ontology.actions.scoreboard_actions import (
    RecordScoreboardObservationRequest,
)
from nutmeg.ontology.actions.workflow_actions import (
    CreateAgentProposalRequest,
    LinkPrecedentRequest,
    RecordAdjudicationRequest,
    RecordFlagInstanceRequest,
    RegisterPredictionRequest,
    ResolveAgentProposalRequest,
)
from nutmeg.ontology.decision.read_flow import ReadMatchRequest
from nutmeg.ontology.identity.models import EntityType
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
from nutmeg.product.readiness import (
    classify_claim_conflicts,
    evaluate_forecast_readiness,
    evaluate_readiness,
)
from nutmeg.product.repository import ProductReadRepository

_ALLOWED_ACTIONS = {
    'commit_forecast',
    'record_adjudication',
    'record_flag_instance',
    'register_prediction',
    'link_precedent',
    'create_agent_proposal',
    'resolve_agent_proposal',
    'merge_entity',
    'verify_claim',
    'dispute_claim',
    'retract_claim',
    'record_scoreboard_observation',
    'apply_factor_status',
    'approve_release',
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
        if request.action_type == 'merge_entity':
            return self._merge_entity(request, actor_id, actor_role, requested_at)
        if request.action_type in {'verify_claim', 'dispute_claim', 'retract_claim'}:
            return self._adjudicate_claim(
                request, actor_id, actor_role, requested_at
            )
        if request.action_type == 'record_scoreboard_observation':
            return self._record_scoreboard_observation(
                request, actor_id, actor_role, requested_at
            )
        if request.action_type == 'apply_factor_status':
            return self._apply_factor_status(
                request, actor_id, actor_role, requested_at
            )
        if request.action_type == 'approve_release':
            return self._approve_release(
                request, actor_id, actor_role, requested_at
            )
        outcome = self._execute_workflow(
            request, actor_id=actor_id, actor_role=actor_role, requested_at=requested_at
        )
        return _response(outcome)

    def _approve_release(
        self,
        request: ProductActionRequest,
        actor_id: str,
        actor_role: ActorRole,
        requested_at: datetime,
    ) -> ProductActionResponse:
        payload = request.payload
        _reject_actor_payload(payload)
        allowed = {
            'release_version',
            'candidate_commit',
            'expected_snapshot_sha256',
            'reason',
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(
                f"approve_release has unknown fields: {', '.join(sorted(unknown))}"
            )
        outcome = self._kernel.reliability_actions.approve_release(
            ApproveReleaseRequest(
                release_version=_required_str(payload, 'release_version'),
                candidate_commit=_required_str(payload, 'candidate_commit'),
                expected_snapshot_sha256=_required_str(
                    payload, 'expected_snapshot_sha256'
                ),
                reason=_required_str(payload, 'reason'),
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=request.idempotency_key,
                requested_at=requested_at,
            )
        )
        return _response(outcome)

    def _record_scoreboard_observation(
        self,
        request: ProductActionRequest,
        actor_id: str,
        actor_role: ActorRole,
        requested_at: datetime,
    ) -> ProductActionResponse:
        payload = request.payload
        _reject_actor_payload(payload)
        outcome = self._kernel.scoreboard_actions.record_observation(
            RecordScoreboardObservationRequest(
                group_key=_required_str(payload, 'group_key'),
                metric_key=_required_str(payload, 'metric_key'),
                tally=_required_str(payload, 'tally'),
                detail=_required_str(payload, 'detail'),
                status=_required_str(payload, 'status'),
                numerator=_optional_float(payload.get('numerator'), 'numerator'),
                denominator=_optional_float(
                    payload.get('denominator'), 'denominator'
                ),
                value=_optional_float(payload.get('value'), 'value'),
                unit=_optional_str(payload.get('unit')),
                evidence_refs=[
                    ObjectRef(ref['object_type'], ref['object_id'])
                    for ref in _reference_list(payload.get('evidence_refs', []))
                ],
                effective_at=_parse_aware(
                    _required_str(payload, 'effective_at'), 'effective_at'
                ),
                supersedes_observation_id=_optional_str(
                    payload.get('supersedes_observation_id')
                ),
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=request.idempotency_key,
                requested_at=requested_at,
            )
        )
        return _response(outcome)

    def _apply_factor_status(
        self,
        request: ProductActionRequest,
        actor_id: str,
        actor_role: ActorRole,
        requested_at: datetime,
    ) -> ProductActionResponse:
        payload = request.payload
        _reject_actor_payload(payload)
        factor_id = _required_str(payload, 'factor_definition_id')
        proposal_id = _required_str(payload, 'proposal_id')
        current_status = _required_str(payload, 'expected_current_status')
        target_status = _required_str(payload, 'target_status')
        adjudication_id = _required_str(payload, 'adjudication_id')
        version_key = f'factor_definition:{factor_id}'
        if version_key not in request.expected_versions:
            raise ValueError(f'expected version {version_key} is required')
        expected_version = request.expected_versions[version_key]
        detail = self._repository.ontology_object(
            'factor_definition', factor_id, as_of=requested_at.isoformat()
        )
        if detail is None:
            raise ProductNotFoundError(f'factor definition {factor_id} not found')
        properties = detail['properties']
        if (
            properties['version'] != expected_version
            or properties['status'] != current_status
        ):
            from nutmeg.ontology.errors import OptimisticConcurrencyError

            raise OptimisticConcurrencyError(
                f'factor {factor_id} no longer matches the expected version/status'
            )
        proposals = self._repository.projection_rows(
            'factor_lifecycle_proposals', as_of=requested_at.isoformat()
        )
        if not self._lifecycle_projection_is_applicable(
            proposals, adjudication_id=adjudication_id
        ):
            raise ProductActionBlockedError('lifecycle projection is not current')
        proposal = next(
            (row for row in proposals['rows'] if row['proposal_id'] == proposal_id),
            None,
        )
        if proposal is None or (
            proposal['factor_definition_id'],
            proposal['from_status'],
            proposal['to_status'],
        ) != (factor_id, current_status, target_status):
            raise ProductActionBlockedError(
                'lifecycle proposal is missing or no longer matches the factor'
            )
        adjudication = self._repository.ontology_object(
            'adjudication', adjudication_id, as_of=requested_at.isoformat()
        )
        if adjudication is None:
            raise ProductNotFoundError(f'adjudication {adjudication_id} not found')
        adjudication_properties = adjudication['properties']
        if (
            adjudication_properties['subject_type'] != 'factor_definition'
            or adjudication_properties['subject_id'] != factor_id
            or adjudication_properties['decision'] != 'apply'
            or adjudication_properties['alternative'].get('proposal_id')
            != proposal_id
            or not str(adjudication_properties['reason']).strip()
        ):
            raise ProductActionBlockedError(
                'a reason-bearing factor adjudication is required'
            )
        return _response(
            self._kernel.factor_actions.apply_factor_status(
                ApplyFactorStatusRequest(
                    factor_definition_id=factor_id,
                    target_status=target_status,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    idempotency_key=request.idempotency_key,
                    requested_at=requested_at,
                    expected_current_status=current_status,
                    expected_factor_version=expected_version,
                    adjudication_id=adjudication_id,
                    proposal_id=proposal_id,
                )
            )
        )

    def _lifecycle_projection_is_applicable(
        self, projection: dict, *, adjudication_id: str
    ) -> bool:
        health = projection['health']
        if health['state'] == 'available':
            return True
        watermark = health.get('source_high_watermark')
        if health['state'] != 'stale' or watermark is None:
            return False
        actions = self._repository.actions_after_high_watermark(int(watermark))
        if len(actions) != 1:
            return False
        [action] = actions
        return (
            action['action_type'] == 'record_adjudication'
            and action['status'] == 'committed'
            and any(
                ref.get('object_type') == 'adjudication'
                and ref.get('object_id') == adjudication_id
                for ref in action['result_refs']
            )
        )

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
        conflicts = classify_claim_conflicts(claims)
        readiness = evaluate_forecast_readiness(
            evaluate_readiness(
                identity_resolved=(
                    match['home_resolution_status'] == 'resolved'
                    and match['away_resolution_status'] == 'resolved'
                ),
                snapshot_at=(
                    _parse_aware(snapshot['as_of'], 'snapshot.as_of')
                    if snapshot
                    else None
                ),
                as_of=cutoff,
                evidence_count=len(observations) + len(claims),
            ),
            blocking_conflicts=sum(item.blocking for item in conflicts),
            provisional_conflicts=sum(not item.blocking for item in conflicts),
        )
        if readiness.level is ReadinessLevel.BLOCKED:
            codes = ', '.join(issue.code for issue in readiness.issues)
            raise ProductActionBlockedError(f'forecast is blocked: {codes}')
        assert snapshot is not None
        belief_distribution = _float_distribution(payload, 'belief_distribution')
        factors = _factors(payload.get('factors', []))
        proposal_id = _optional_str(payload.get('agent_proposal_id'))
        if proposal_id is not None:
            self._validate_forecast_proposal(
                request,
                match_id=match_id,
                proposal_id=proposal_id,
                belief_distribution=belief_distribution,
            )

        if actor_role is not ActorRole.JUDGE_OPERATOR:
            outcome = self._kernel.forecast_actions.commit_forecast(
                CommitForecastRequest(
                    match_id=match_id,
                    market_definition_id=market_id,
                    decision_session_id=None,
                    prior_distribution=snapshot['fair_distribution'],
                    belief_distribution=belief_distribution,
                    factors=factors,
                    commitment_tier=str(payload.get('commitment_tier', 'judged')),
                    evidence_bundle_id=None,
                    prior_snapshot_id=snapshot['market_snapshot_id'],
                    falsifier=_optional_str(payload.get('falsifier')),
                    actor_id=actor_id,
                    actor_role=actor_role,
                    idempotency_key=request.idempotency_key,
                    requested_at=requested_at,
                    information_cutoff_at=cutoff.isoformat(),
                    expected_current_revision_no=request.expected_versions[version_key],
                )
            )
            return _response(outcome)

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
                belief_distribution=belief_distribution,
                factors=factors,
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

    def _validate_forecast_proposal(
        self,
        request: ProductActionRequest,
        *,
        match_id: str,
        proposal_id: str,
        belief_distribution: dict[str, float],
    ) -> None:
        proposal = self._repository.agent_proposal(proposal_id)
        if proposal is None:
            raise ProductNotFoundError(f'agent proposal {proposal_id} not found')
        version_key = f'agent_proposal:{proposal_id}'
        if version_key not in request.expected_versions:
            raise ValueError(f'expected version {version_key} is required')
        expected_version = request.expected_versions[version_key]
        if proposal['version'] != expected_version:
            from nutmeg.ontology.errors import OptimisticConcurrencyError

            raise OptimisticConcurrencyError(
                f'proposal {proposal_id} is at version {proposal["version"]}, '
                f'expected {expected_version}'
            )
        if (
            proposal['subject_type'] != 'match'
            or proposal['subject_id'] != match_id
            or proposal['status'] != 'approved'
        ):
            raise ProductActionBlockedError(
                'forecast proposal must be approved for the same match'
            )
        proposed = proposal['payload'].get('proposed_belief')
        if not isinstance(proposed, dict):
            raise ProductActionBlockedError('proposal belief is missing')
        proposed_belief = {
            str(key): float(value) for key, value in proposed.items()
        }
        if proposed_belief != belief_distribution:
            raise ProductActionBlockedError(
                'forecast belief does not match the approved proposal belief'
            )

    def _adjudicate_claim(
        self,
        request: ProductActionRequest,
        actor_id: str,
        actor_role: ActorRole,
        requested_at: datetime,
    ) -> ProductActionResponse:
        claim_id = _required_str(request.payload, 'claim_id')
        if self._repository.claim(claim_id) is None:
            raise ProductNotFoundError(f'claim {claim_id} not found')
        command = ClaimAdjudicationRequest(
            claim_id=claim_id,
            actor_id=actor_id,
            actor_role=actor_role,
            idempotency_key=request.idempotency_key,
            requested_at=requested_at,
        )
        action = {
            'verify_claim': self._kernel.claim_actions.verify_claim,
            'dispute_claim': self._kernel.claim_actions.dispute_claim,
            'retract_claim': self._kernel.claim_actions.retract_claim,
        }[request.action_type]
        return _response(action(command))

    def _merge_entity(
        self,
        request: ProductActionRequest,
        actor_id: str,
        actor_role: ActorRole,
        requested_at: datetime,
    ) -> ProductActionResponse:
        payload = request.payload
        entity_type = _required_str(payload, 'entity_type')
        if entity_type != EntityType.TEAM.value:
            raise ValueError('M2 identity merge supports team entities only')
        from_id = _required_str(payload, 'from_id')
        into_id = _required_str(payload, 'into_id')
        if from_id == into_id:
            raise ValueError('cannot merge an entity into itself')
        for entity_id in (from_id, into_id):
            if self._repository.identity_item(entity_type, entity_id) is None:
                raise ProductNotFoundError(f'team {entity_id} not found')

        outcome = self._kernel.entity_actions.merge_entity(
            MergeEntityRequest(
                entity_type=EntityType.TEAM,
                from_id=from_id,
                into_id=into_id,
                reason=_required_str(payload, 'reason'),
                evidence_retrieval_ids=tuple(
                    _string_list(payload.get('evidence_retrieval_ids', []))
                ),
                actor_id=actor_id,
                actor_role=actor_role,
                idempotency_key=request.idempotency_key,
                requested_at=requested_at,
            )
        )
        return _response(outcome)

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
            match_id = _required_str(payload, 'match_id')
            return self._kernel.workflow.register_prediction(
                RegisterPredictionRequest(
                    match_id=match_id,
                    subject_type='match',
                    subject_id=match_id,
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
                    information_cutoff_at=_required_str(
                        payload, 'information_cutoff_at'
                    ),
                    operator_prompt=_required_str(payload, 'operator_prompt'),
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


def _optional_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a number or null')
    return float(value)


def _reject_actor_payload(payload: dict[str, object]) -> None:
    if 'actor_id' in payload or 'actor_role' in payload:
        raise ValueError('actor identity and role are server-derived')


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
