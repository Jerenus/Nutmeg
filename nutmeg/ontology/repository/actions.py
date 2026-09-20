"""Action persistence and idempotency queries.

The Action log is the audit spine of the kernel: every accepted, committed,
rejected and failed write leaves exactly one row keyed by its idempotency key.
Enum and JSON columns round-trip through the canonical serializer; a persisted
value that does not map back to a known enum raises rather than silently
defaulting.
"""
from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import Connection, RowMapping, func, insert, select, update

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActionStatus,
    ActorRole,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.repository import schema


@dataclass(frozen=True, slots=True)
class ActionRecord:
    action_id: str
    action_type: str
    actor_id: str
    actor_role: ActorRole
    requested_at: str
    idempotency_key: str
    request_hash: str
    expected_versions: dict[str, int]
    payload: dict[str, object]
    policy_version: str
    historical_replay: bool
    replay_run_id: str | None
    status: ActionStatus
    result_refs: tuple[ObjectRef, ...]
    error_code: str | None
    error_detail: str | None
    committed_at: str | None


def _refs_to_json(result_refs: tuple[ObjectRef, ...]) -> str:
    return canonical_json([ref.to_dict() for ref in result_refs])


class ActionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def release_failed_idempotency_key(self, key: str, action_id: str) -> None:
        """Free a FAILED attempt's key so an identical retry can execute.

        The audit row survives under a derived key; only terminal FAILED rows
        are eligible — committed and rejected outcomes stay replayable.
        """
        self._connection.execute(
            update(schema.actions)
            .where(
                schema.actions.c.action_id == action_id,
                schema.actions.c.idempotency_key == key,
                schema.actions.c.status == ActionStatus.FAILED.value,
            )
            .values(idempotency_key=f'{key}#failed-{action_id}')
        )

    def get_by_idempotency_key(self, key: str) -> ActionRecord | None:
        row = (
            self._connection.execute(
                select(schema.actions).where(schema.actions.c.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return self._to_record(row)

    def count(
        self,
        *,
        action_type: str | None = None,
        status: ActionStatus | None = None,
        idempotency_prefix: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(schema.actions)
        if action_type is not None:
            query = query.where(schema.actions.c.action_type == action_type)
        if status is not None:
            query = query.where(schema.actions.c.status == status.value)
        if idempotency_prefix is not None:
            query = query.where(
                schema.actions.c.idempotency_key.startswith(idempotency_prefix)
            )
        return self._connection.execute(query).scalar_one()

    def latest_committed(self, action_type: str) -> ActionRecord | None:
        row = (
            self._connection.execute(
                select(schema.actions)
                .where(
                    schema.actions.c.action_type == action_type,
                    schema.actions.c.status == ActionStatus.COMMITTED.value,
                )
                .order_by(
                    schema.actions.c.committed_at.desc(),
                    schema.actions.c.action_id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return None if row is None else self._to_record(row)

    def count_committed_snapshot_matches(
        self,
        match_ids: Collection[str],
        *,
        provider: str,
        snapshot_kind: str,
    ) -> int:
        if not match_ids:
            return 0
        match_id = func.json_extract(schema.actions.c.payload_json, "$.match_id")
        query = (
            select(func.count(func.distinct(match_id)))
            .select_from(schema.actions)
            .where(
                schema.actions.c.action_type == "build_market_snapshot",
                schema.actions.c.status == ActionStatus.COMMITTED.value,
                match_id.in_(tuple(match_ids)),
                func.json_extract(schema.actions.c.payload_json, "$.provider") == provider,
                func.json_extract(schema.actions.c.payload_json, "$.snapshot_kind")
                == snapshot_kind,
            )
        )
        return self._connection.execute(query).scalar_one()

    def insert_accepted(self, command: ActionCommand) -> None:
        self._connection.execute(
            insert(schema.actions).values(
                action_id=command.action_id,
                action_type=command.action_type,
                actor_id=command.actor_id,
                actor_role=command.actor_role.value,
                requested_at=command.requested_at,
                idempotency_key=command.idempotency_key,
                request_hash=command.request_hash,
                expected_versions_json=canonical_json(command.expected_versions),
                payload_json=canonical_json(command.payload),
                policy_version=command.policy_version,
                status=ActionStatus.ACCEPTED.value,
                result_refs_json='[]',
                error_code=None,
                error_detail=None,
                committed_at=None,
                historical_replay=int(command.historical_replay),
                replay_run_id=command.replay_run_id,
            )
        )

    def mark_committed(
        self,
        action_id: str,
        result_refs: tuple[ObjectRef, ...],
        committed_at: str,
    ) -> None:
        self._connection.execute(
            update(schema.actions)
            .where(schema.actions.c.action_id == action_id)
            .values(
                status=ActionStatus.COMMITTED.value,
                result_refs_json=_refs_to_json(result_refs),
                committed_at=committed_at,
            )
        )

    def insert_terminal(
        self,
        command: ActionCommand,
        status: ActionStatus,
        error_code: str | None,
        error_detail: str | None,
    ) -> None:
        self._connection.execute(
            insert(schema.actions).values(
                action_id=command.action_id,
                action_type=command.action_type,
                actor_id=command.actor_id,
                actor_role=command.actor_role.value,
                requested_at=command.requested_at,
                idempotency_key=command.idempotency_key,
                request_hash=command.request_hash,
                expected_versions_json=canonical_json(command.expected_versions),
                payload_json=canonical_json(command.payload),
                policy_version=command.policy_version,
                status=status.value,
                result_refs_json='[]',
                error_code=error_code,
                error_detail=error_detail,
                committed_at=None,
                historical_replay=int(command.historical_replay),
                replay_run_id=command.replay_run_id,
            )
        )

    @staticmethod
    def to_outcome(record: ActionRecord) -> ActionOutcome:
        return ActionOutcome(
            action_id=record.action_id,
            action_type=record.action_type,
            status=record.status,
            result_refs=record.result_refs,
            error_code=record.error_code,
            error_detail=record.error_detail,
            committed_at=record.committed_at,
        )

    @staticmethod
    def _to_record(row: RowMapping) -> ActionRecord:
        return ActionRecord(
            action_id=row['action_id'],
            action_type=row['action_type'],
            actor_id=row['actor_id'],
            actor_role=ActorRole(row['actor_role']),
            requested_at=row['requested_at'],
            idempotency_key=row['idempotency_key'],
            request_hash=row['request_hash'],
            expected_versions=json.loads(row['expected_versions_json']),
            payload=json.loads(row['payload_json']),
            policy_version=row['policy_version'],
            historical_replay=bool(row['historical_replay']),
            replay_run_id=row['replay_run_id'],
            status=ActionStatus(row['status']),
            result_refs=tuple(
                ObjectRef(item['object_type'], item['object_id'])
                for item in json.loads(row['result_refs_json'])
            ),
            error_code=row['error_code'],
            error_detail=row['error_detail'],
            committed_at=row['committed_at'],
        )
