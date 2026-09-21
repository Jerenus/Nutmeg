"""Idempotent Action execution with atomic business + audit commit.

``execute`` is the single funnel every formal write goes through. ``execute_batch``
extends the same contract to related Actions that must commit together:

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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError, OperationalError

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActionStatus,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.permissions import PermissionGuard
from nutmeg.ontology.errors import IdempotencyConflictError, PermissionDeniedError
from nutmeg.ontology.repository.actions import ActionRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

ActionHandler = Callable[[OntologyUnitOfWork, ActionCommand], tuple[ObjectRef, ...]]
ActionBatchItem = tuple[ActionCommand, ActionHandler]

UnitOfWorkFactory = Callable[[], OntologyUnitOfWork]


@dataclass(frozen=True, slots=True)
class ReplayActionContext:
    replay_run_id: str
    business_date: str
    isolated_database_identity: str


_REPLAY_PROTECTED_ACTIONS = frozenset(
    {
        "approve_jczq_ontology_cutover",
        "confirm_ticket_placement",
        "issue_ticket_confirmation",
        "record_cash_transaction",
        "rsi_approve_deployment",
        "rsi_fulfill_duty",
        "approve_policy_deployment",
        "trip_policy_brake",
    }
)


class _ReplayBindingError(PermissionDeniedError):
    """A replay envelope that cannot be safely persisted against its claimed run."""

# Backoff for looking up a concurrent same-key winner after a unique/lock race.
_RACE_RETRY_DELAYS = (0.01, 0.02, 0.03, 0.04, 0.05)


def _is_same_key_race(error: Exception) -> bool:
    """True only for an Actions idempotency-key unique clash or a SQLite lock."""
    message = str(error).lower()
    return "idempotency_key" in message or "database is locked" in message


class ActionService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        replay_context: ReplayActionContext | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._replay_context = replay_context

    def unit_of_work(self):
        """Open the same governed UOW used by Actions for typed result hydration."""
        return self._unit_of_work_factory()

    def bind_replay(self, context: ReplayActionContext) -> ActionService:
        if self._replay_context is not None and self._replay_context != context:
            raise PermissionDeniedError("nested caller cannot replace the bound replay run id")
        return ActionService(self._unit_of_work_factory, replay_context=context)

    def execute(
        self,
        command: ActionCommand,
        handler: ActionHandler,
        *,
        acquire_write_lock: bool = False,
    ) -> ActionOutcome:
        command = self._bind_replay_command(command)
        existing = self._lookup(command.idempotency_key)
        if existing is not None:
            if existing.status is ActionStatus.FAILED:
                # A FAILED attempt holds no claim on the key — not even against a
                # *corrected* retry. Checking the request hash first made a failed
                # attempt block the fix for it: the 2026-09-11 scoreboard mirror
                # failed for a missing `--supersedes`, and every retry that added one
                # was then rejected as "reused with a different request", so the only
                # way through was to perturb the payload. Keep the audit row under a
                # derived key and execute the corrected request afresh.
                with self._unit_of_work_factory() as uow:
                    uow.actions.release_failed_idempotency_key(
                        command.idempotency_key, existing.action_id
                    )
            elif existing.request_hash != command.request_hash:
                raise IdempotencyConflictError(
                    f"idempotency key {command.idempotency_key} was reused with a different request"
                )
            else:
                return ActionRepository.to_outcome(existing)

        try:
            with self._unit_of_work_factory() as uow:
                if acquire_write_lock:
                    uow.acquire_write_lock()
                self._validate_replay_run(uow, command)
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
        except _ReplayBindingError:
            raise
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

    def execute_batch(self, items: Iterable[ActionBatchItem]) -> tuple[ActionOutcome, ...]:
        """Preflight and atomically commit a related batch of Actions."""
        batch = tuple(
            (self._bind_replay_command(command), handler)
            for command, handler in items
        )
        if not batch:
            return ()
        self._assert_distinct_batch_keys(batch)

        with self._unit_of_work_factory() as uow:
            existing_by_key = {}
            for command, _handler in batch:
                existing = uow.actions.get_by_idempotency_key(command.idempotency_key)
                if (
                    existing is not None
                    and existing.status is not ActionStatus.FAILED
                    and existing.request_hash != command.request_hash
                ):
                    # FAILED rows are audit, not a claim — a corrected retry must pass.
                    raise IdempotencyConflictError(
                        f"idempotency key {command.idempotency_key} was reused with "
                        "a different request"
                    )
                existing_by_key[command.idempotency_key] = existing

            guard = PermissionGuard(uow.connection)
            for command, _handler in batch:
                self._validate_replay_run(uow, command)
                guard.assert_allowed(
                    command.policy_version,
                    command.action_type,
                    command.actor_role,
                )

            outcomes: list[ActionOutcome] = []
            for command, handler in batch:
                existing = existing_by_key[command.idempotency_key]
                if existing is not None and existing.status is not ActionStatus.FAILED:
                    outcomes.append(ActionRepository.to_outcome(existing))
                    continue
                if existing is not None:
                    uow.actions.release_failed_idempotency_key(
                        command.idempotency_key,
                        existing.action_id,
                    )

                uow.actions.insert_accepted(command)
                result_refs = tuple(handler(uow, command))
                committed_at = datetime.now(UTC).isoformat()
                uow.actions.mark_committed(command.action_id, result_refs, committed_at)
                uow.outbox.append_for_action(
                    command,
                    ActionStatus.COMMITTED,
                    result_refs,
                    committed_at,
                )
                outcomes.append(
                    ActionOutcome(
                        action_id=command.action_id,
                        action_type=command.action_type,
                        status=ActionStatus.COMMITTED,
                        result_refs=result_refs,
                        committed_at=committed_at,
                    )
                )
        return tuple(outcomes)

    def _bind_replay_command(self, command: ActionCommand) -> ActionCommand:
        context = self._replay_context
        if context is None:
            if command.actor_role is ActorRole.REPLAY_ADJUDICATOR:
                raise PermissionDeniedError(
                    "replay_adjudicator requires a replay-bound Action service"
                )
            return command
        if command.action_type in _REPLAY_PROTECTED_ACTIONS:
            raise PermissionDeniedError(
                f"protected action {command.action_type} is forbidden in historical replay"
            )
        if command.replay_run_id not in (None, context.replay_run_id):
            raise PermissionDeniedError("nested caller cannot replace the bound replay run id")
        return ActionCommand.create(
            action_type=command.action_type,
            actor_id=command.actor_id,
            actor_role=command.actor_role,
            idempotency_key=command.idempotency_key,
            payload=command.payload,
            requested_at=datetime.fromisoformat(command.requested_at),
            expected_versions=command.expected_versions,
            policy_version=command.policy_version,
            action_id=command.action_id,
            historical_replay=True,
            replay_run_id=context.replay_run_id,
        )

    def _validate_replay_run(
        self, uow: OntologyUnitOfWork, command: ActionCommand
    ) -> None:
        context = self._replay_context
        if context is None:
            return
        run = uow.replay.get(context.replay_run_id)
        database_identity = str(Path(uow.connection.engine.url.database).resolve())
        command_date = command.payload.get("business_date")
        if run is not None and run.status != "running":
            raise _ReplayBindingError("historical replay run is not active")
        if (
            run is None
            or run.business_date != context.business_date
            or run.isolated_database_identity != context.isolated_database_identity
            or database_identity != context.isolated_database_identity
            or (command_date is not None and command_date != context.business_date)
        ):
            raise _ReplayBindingError("replay run binding is invalid")

    @staticmethod
    def _assert_distinct_batch_keys(batch: tuple[ActionBatchItem, ...]) -> None:
        seen: set[str] = set()
        for command, _handler in batch:
            if command.idempotency_key in seen:
                raise IdempotencyConflictError(
                    f"duplicate idempotency key {command.idempotency_key} in Action batch"
                )
            seen.add(command.idempotency_key)

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
