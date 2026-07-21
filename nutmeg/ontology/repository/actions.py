"""Action persistence and idempotency queries.

The Action log is the audit spine of the kernel: every accepted, committed,
rejected and failed write leaves exactly one row keyed by its idempotency key.
Enum and JSON columns round-trip through the canonical serializer; a persisted
value that does not map back to a known enum raises rather than silently
defaulting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, RowMapping, insert, select, update

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
            status=ActionStatus(row['status']),
            result_refs=tuple(
                ObjectRef(item['object_type'], item['object_id'])
                for item in json.loads(row['result_refs_json'])
            ),
            error_code=row['error_code'],
            error_detail=row['error_detail'],
            committed_at=row['committed_at'],
        )
