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
            },
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            uow.decision.set_factor_status(request.factor_definition_id, target.value)
            return (ObjectRef('factor_definition', request.factor_definition_id),)

        return self._action_service.execute(command, handler)
