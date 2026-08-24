"""Factor status lifecycle Actions.

`propose_factor_status` (ai_analyst/judge) records the intent to transition a
factor — the aggregate skill/CLV verdict that justifies it is a Package 4
projection, so here it only audits the proposal. `apply_factor_status`
(judge_operator only) executes the transition probation→active→retired. AI can
propose but never apply.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.decision.models import FactorStatus
from nutmeg.ontology.errors import OptimisticConcurrencyError


@dataclass(frozen=True, slots=True)
class ProposeFactorStatusRequest:
    factor_definition_id: str
    target_status: str
    rationale: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ApplyFactorStatusRequest:
    factor_definition_id: str
    target_status: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime
    expected_current_status: str | None = None
    expected_factor_version: int | None = None
    adjudication_id: str | None = None
    proposal_id: str | None = None


class FactorActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def propose_factor_status(self, request: ProposeFactorStatusRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type='propose_factor_status',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                'factor_definition_id': request.factor_definition_id,
                'target_status': request.target_status,
                'rationale': request.rationale,
            },
            requested_at=request.requested_at,
        )

        def handler(_uow, _command) -> tuple[ObjectRef, ...]:
            # Audit-only: the aggregate verdict lives in Package 4; no status change here.
            return (ObjectRef('factor_definition', request.factor_definition_id),)

        return self._action_service.execute(command, handler)

    def apply_factor_status(self, request: ApplyFactorStatusRequest) -> ActionOutcome:
        target = FactorStatus(request.target_status)   # rejects an unknown status
        command = ActionCommand.create(
            action_type='apply_factor_status',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={
                'factor_definition_id': request.factor_definition_id,
                'target_status': target.value,
                'expected_current_status': request.expected_current_status,
                'expected_factor_version': request.expected_factor_version,
                'adjudication_id': request.adjudication_id,
                'proposal_id': request.proposal_id,
            },
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            definition = uow.decision.factor_definition(request.factor_definition_id)
            if definition is None:
                raise ValueError(
                    f'factor definition {request.factor_definition_id} does not exist'
                )
            if (
                request.expected_factor_version is not None
                and definition.version != request.expected_factor_version
            ):
                raise OptimisticConcurrencyError(
                    f'factor {request.factor_definition_id} is at version '
                    f'{definition.version}, expected {request.expected_factor_version}'
                )
            if (
                request.expected_current_status is not None
                and definition.status != request.expected_current_status
            ):
                raise OptimisticConcurrencyError(
                    f'factor {request.factor_definition_id} is {definition.status}, '
                    f'expected {request.expected_current_status}'
                )
            refs = [ObjectRef('factor_definition', request.factor_definition_id)]
            if request.adjudication_id is not None:
                adjudication = uow.workflow.get_adjudication(request.adjudication_id)
                if (
                    adjudication.subject_type != 'factor_definition'
                    or adjudication.subject_id != request.factor_definition_id
                    or adjudication.decision != 'apply'
                    or (
                        request.proposal_id is not None
                        and adjudication.alternative.get('proposal_id')
                        != request.proposal_id
                    )
                    or not adjudication.reason.strip()
                ):
                    raise ValueError(
                        'factor status adjudication must contain a reason and target '
                        'the factor definition'
                    )
                refs.append(ObjectRef('adjudication', request.adjudication_id))
            uow.decision.set_factor_status(request.factor_definition_id, target.value)
            return tuple(refs)

        return self._action_service.execute(command, handler)
