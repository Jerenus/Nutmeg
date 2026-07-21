"""OpenDecisionSession — make "we deliberately looked at this slate" a formal act.

A session records the operator, cutoff and match scope for a round of reading, so
following the market or standing pat is an explicit decision rather than an absent
shadow. judge_operator / deterministic_system only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.decision.models import SessionStatus, mint_decision_id
from nutmeg.ontology.repository.decision import SessionRow


@dataclass(frozen=True, slots=True)
class OpenSessionRequest:
    operator_id: str
    cutoff_at: str
    scope: dict[str, object]
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not self.operator_id.strip():
            raise ValueError('operator_id is required')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class SessionActions:
    def __init__(self, action_service: ActionService) -> None:
        self._action_service = action_service

    def open_session(self, request: OpenSessionRequest) -> ActionOutcome:
        command = ActionCommand.create(
            action_type='open_decision_session',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload={'operator_id': request.operator_id, 'cutoff_at': request.cutoff_at},
            requested_at=request.requested_at,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            session_id = mint_decision_id('sess')
            opened_at = request.requested_at.astimezone(UTC).isoformat()
            uow.decision.insert_session(
                SessionRow(
                    decision_session_id=session_id,
                    opened_at=opened_at,
                    operator_id=request.operator_id,
                    cutoff_at=request.cutoff_at,
                    scope=request.scope,
                    status=SessionStatus.OPEN.value,
                    closed_at=None,
                )
            )
            return (ObjectRef('decision_session', session_id),)

        return self._action_service.execute(command, handler)
