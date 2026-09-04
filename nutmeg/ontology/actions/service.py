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

import time
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError, OperationalError

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

# Backoff for looking up a concurrent same-key winner after a unique/lock race.
_RACE_RETRY_DELAYS = (0.01, 0.02, 0.03, 0.04, 0.05)


def _is_same_key_race(error: Exception) -> bool:
    """True only for an Actions idempotency-key unique clash or a SQLite lock."""
    message = str(error).lower()
    return "idempotency_key" in message or "database is locked" in message


class ActionService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def unit_of_work(self):
        """Open the same governed UOW used by Actions for typed result hydration."""
        return self._unit_of_work_factory()

    def execute(self, command: ActionCommand, handler: ActionHandler) -> ActionOutcome:
        existing = self._lookup(command.idempotency_key)
        if existing is not None:
            if existing.request_hash != command.request_hash:
                raise IdempotencyConflictError(
                    f"idempotency key {command.idempotency_key} was reused with a different request"
                )
            if existing.status is not ActionStatus.FAILED:
                return ActionRepository.to_outcome(existing)
            # A FAILED attempt must not satisfy a retry as if it were a result:
            # keep the audit row under a derived key and execute afresh.
            with self._unit_of_work_factory() as uow:
                uow.actions.release_failed_idempotency_key(
                    command.idempotency_key, existing.action_id
                )

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
                uow.outbox.append_for_action(
                    command, ActionStatus.COMMITTED, result_refs, committed_at
                )
        except PermissionDeniedError as error:
            return self._audit_terminal(
                command, ActionStatus.REJECTED, "permission_denied", str(error)
            )
        except (IntegrityError, OperationalError) as error:
            # A concurrent writer may have won this idempotency key between our
            # lookup and our insert. Replay the winner's outcome if one appears;
            # otherwise treat it as a genuine failure.
            if _is_same_key_race(error):
                replayed = self._replay_committed_winner(command)
                if replayed is not None:
                    return replayed
            self._audit_terminal(command, ActionStatus.FAILED, "handler_error", str(error))
            raise
        except Exception as error:
            self._audit_terminal(command, ActionStatus.FAILED, "handler_error", str(error))
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

    def _replay_committed_winner(self, command: ActionCommand) -> ActionOutcome | None:
        for delay in _RACE_RETRY_DELAYS:
            time.sleep(delay)
            existing = self._lookup(command.idempotency_key)
            if existing is None:
                continue
            if existing.request_hash != command.request_hash:
                raise IdempotencyConflictError(
                    f"idempotency key {command.idempotency_key} was reused with a different request"
                )
            return ActionRepository.to_outcome(existing)
        return None

    def _audit_terminal(
        self,
        command: ActionCommand,
        status: ActionStatus,
        error_code: str,
        error_detail: str,
    ) -> ActionOutcome:
        occurred_at = datetime.now(UTC).isoformat()
        with self._unit_of_work_factory() as uow:
            uow.actions.insert_terminal(command, status, error_code, error_detail)
            uow.outbox.append_for_action(command, status, (), occurred_at)
        return ActionOutcome(
            action_id=command.action_id,
            action_type=command.action_type,
            status=status,
            error_code=error_code,
            error_detail=error_detail,
        )
