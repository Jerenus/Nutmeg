"""Idempotent Action execution with atomic business + audit commit.

``execute`` is the single funnel every formal write goes through:

1. look up the idempotency key in a read transaction;
2. if found, replay its stored outcome — or reject a reused key that now carries
   a different request;
3. otherwise, in one write transaction: check permission, record the accepted
   Action, run the handler's business writes, and mark the Action committed —
   all committing together;
4. a permission denial is audited as a ``rejected`` Action and returned;
5. any other handler failure rolls the business rows back, audits a ``failed``
   Action, and re-raises the original error.

Concurrent unique-key race recovery is intentionally deferred to Task 12; this
service adds no untested retry logic.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActionStatus,
    ObjectRef,
)
from nutmeg.ontology.actions.permissions import PermissionGuard
from nutmeg.ontology.errors import IdempotencyConflictError, PermissionDeniedError
from nutmeg.ontology.repository.actions import ActionRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

ActionHandler = Callable[[OntologyUnitOfWork, ActionCommand], tuple[ObjectRef, ...]]

UnitOfWorkFactory = Callable[[], OntologyUnitOfWork]


class ActionService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: ActionCommand, handler: ActionHandler) -> ActionOutcome:
        existing = self._lookup(command.idempotency_key)
        if existing is not None:
            if existing.request_hash != command.request_hash:
                raise IdempotencyConflictError(
                    f'idempotency key {command.idempotency_key} was reused '
                    f'with a different request'
                )
            return ActionRepository.to_outcome(existing)

        try:
            with self._unit_of_work_factory() as uow:
                PermissionGuard(uow.connection).assert_allowed(
                    command.policy_version, command.action_type, command.actor_role
                )
                repository = uow.actions
                repository.insert_accepted(command)
                result_refs = tuple(handler(uow, command))
                committed_at = datetime.now(UTC).isoformat()
                repository.mark_committed(command.action_id, result_refs, committed_at)
        except PermissionDeniedError as error:
            return self._audit_terminal(
                command, ActionStatus.REJECTED, 'permission_denied', str(error)
            )
        except Exception as error:
            self._audit_terminal(command, ActionStatus.FAILED, 'handler_error', str(error))
            raise

        return ActionOutcome(
            action_id=command.action_id,
            action_type=command.action_type,
            status=ActionStatus.COMMITTED,
            result_refs=result_refs,
            committed_at=committed_at,
        )

    def _lookup(self, idempotency_key: str):
        with self._unit_of_work_factory() as uow:
            return uow.actions.get_by_idempotency_key(idempotency_key)

    def _audit_terminal(
        self,
        command: ActionCommand,
        status: ActionStatus,
        error_code: str,
        error_detail: str,
    ) -> ActionOutcome:
        with self._unit_of_work_factory() as uow:
            uow.actions.insert_terminal(command, status, error_code, error_detail)
        return ActionOutcome(
            action_id=command.action_id,
            action_type=command.action_type,
            status=status,
            error_code=error_code,
            error_detail=error_detail,
        )
