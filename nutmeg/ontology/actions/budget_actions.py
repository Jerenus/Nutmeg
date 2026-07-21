"""ChangeBudgetPolicy — the ¥400 budget is versioned policy data, not scattered ifs.

Each change writes a new active ``budget_policies`` row (total + bucket caps).
judge_operator only; policy changes are themselves audited Actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.finance.models import mint_finance_id
from nutmeg.ontology.repository.finance import BudgetPolicyRow


@dataclass(frozen=True, slots=True)
class ChangeBudgetPolicyRequest:
    channel: str
    total_cap: float
    bucket_caps: dict[str, float]
    policy_version: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if self.total_cap < 0:
            raise ValueError('total_cap must be non-negative')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class BudgetActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def change_budget_policy(self, request: ChangeBudgetPolicyRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type='change_budget_policy',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={'channel': request.channel, 'total_cap': request.total_cap},
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            at = request.requested_at.astimezone(UTC).isoformat()
            budget_policy_id = mint_finance_id('bp')
            uow.finance.insert_budget_policy(
                BudgetPolicyRow(
                    budget_policy_id=budget_policy_id,
                    policy_version=request.policy_version,
                    channel=request.channel,
                    total_cap=request.total_cap,
                    bucket_caps=request.bucket_caps,
                    status='active',
                    effective_at=at,
                    created_at=at,
                )
            )
            return (ObjectRef('budget_policy', budget_policy_id),)

        return self._action_service.execute(command, handler)
