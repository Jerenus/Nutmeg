"""Durable Action event outbox with monotonically increasing cursors."""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import Connection, func, insert, select, update

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionStatus,
    ObjectRef,
    canonical_json,
)
from nutmeg.ontology.repository import schema_workflow as sw


@dataclass(frozen=True, slots=True)
class OutboxEventRow:
    sequence: int
    event_id: str
    action_id: str
    topic: str
    object_type: str | None
    object_id: str | None
    payload: dict[str, object]
    occurred_at: str


class OutboxRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def append_for_action(
        self,
        command: ActionCommand,
        status: ActionStatus,
        result_refs: tuple[ObjectRef, ...],
        occurred_at: str,
    ) -> None:
        primary = result_refs[0] if result_refs else None
        self._connection.execute(
            insert(sw.outbox_events).values(
                event_id=f'evt-{uuid4().hex}',
                action_id=command.action_id,
                topic=f'action.{status.value}',
                object_type=primary.object_type if primary else None,
                object_id=primary.object_id if primary else None,
                payload_json=canonical_json(
                    {
                        'action_type': command.action_type,
                        'status': status.value,
                        'result_refs': [ref.to_dict() for ref in result_refs],
                    }
                ),
                occurred_at=occurred_at,
            )
        )

    def after(self, sequence: int, *, limit: int) -> list[OutboxEventRow]:
        rows = (
            self._connection.execute(
                select(sw.outbox_events)
                .where(sw.outbox_events.c.sequence > sequence)
                .order_by(sw.outbox_events.c.sequence)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [self._to_row(row) for row in rows]

    def count(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(sw.outbox_events)
        ).scalar_one()

    def latest_sequence(self) -> int:
        value = self._connection.execute(
            select(func.max(sw.outbox_events.c.sequence))
        ).scalar_one()
        return int(value or 0)

    def consumer_cursor(self, consumer_name: str) -> int:
        name = consumer_name.strip()
        if not name:
            raise ValueError("consumer_name is required")
        value = self._connection.execute(
            select(sw.operator_projection_cursors.c.last_sequence).where(
                sw.operator_projection_cursors.c.consumer_name == name
            )
        ).scalar_one_or_none()
        return int(value or 0)

    def advance_consumer_cursor(
        self,
        consumer_name: str,
        *,
        expected_sequence: int,
        next_sequence: int,
        updated_at: str,
    ) -> None:
        name = consumer_name.strip()
        if not name:
            raise ValueError("consumer_name is required")
        if expected_sequence < 0 or next_sequence < expected_sequence:
            raise ValueError("consumer cursor must advance monotonically")
        result = self._connection.execute(
            update(sw.operator_projection_cursors)
            .where(
                sw.operator_projection_cursors.c.consumer_name == name,
                sw.operator_projection_cursors.c.last_sequence == expected_sequence,
            )
            .values(last_sequence=next_sequence, updated_at=updated_at)
        )
        if result.rowcount == 1:
            return
        if expected_sequence != 0 or self.consumer_cursor(name) != 0:
            raise ValueError("consumer cursor changed concurrently")
        self._connection.execute(
            insert(sw.operator_projection_cursors).values(
                consumer_name=name,
                last_sequence=next_sequence,
                updated_at=updated_at,
            )
        )

    @staticmethod
    def _to_row(row) -> OutboxEventRow:
        return OutboxEventRow(
            sequence=row['sequence'],
            event_id=row['event_id'],
            action_id=row['action_id'],
            topic=row['topic'],
            object_type=row['object_type'],
            object_id=row['object_id'],
            payload=json.loads(row['payload_json']),
            occurred_at=row['occurred_at'],
        )
