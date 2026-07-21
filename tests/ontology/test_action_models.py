from datetime import UTC, datetime

import pytest

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionStatus,
    ActorRole,
    ObjectRef,
)


def test_request_hash_is_stable_across_mapping_order() -> None:
    now = datetime(2026, 7, 21, 8, tzinfo=UTC)
    left = ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="source:sporttery",
        actor_role=ActorRole.CONNECTOR,
        idempotency_key="sporttery:payload:1",
        payload={"source": "sporttery", "meta": {"b": 2, "a": 1}},
        requested_at=now,
    )
    right = ActionCommand.create(
        action_type="ingest_artifact",
        actor_id="source:sporttery",
        actor_role=ActorRole.CONNECTOR,
        idempotency_key="sporttery:payload:1",
        payload={"meta": {"a": 1, "b": 2}, "source": "sporttery"},
        requested_at=now,
    )
    assert left.request_hash == right.request_hash
    assert left.action_id != right.action_id


def test_command_rejects_naive_time_and_blank_identity() -> None:
    with pytest.raises(ValueError, match="requested_at must be timezone-aware"):
        ActionCommand.create(
            action_type="ingest_artifact",
            actor_id="source",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="key",
            payload={},
            requested_at=datetime(2026, 7, 21, 8),
        )
    with pytest.raises(ValueError, match="idempotency_key is required"):
        ActionCommand.create(
            action_type="ingest_artifact",
            actor_id="source",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key=" ",
            payload={},
            requested_at=datetime.now(UTC),
        )
    with pytest.raises(ValueError, match="expected version must be a non-negative integer"):
        ActionCommand.create(
            action_type="ingest_artifact",
            actor_id="source",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="version-key",
            payload={},
            expected_versions={"source_artifact:sha256:abc": -1},
            requested_at=datetime.now(UTC),
        )


def test_object_ref_and_status_contract() -> None:
    ref = ObjectRef("source_artifact", "sha256:abc")
    assert ref.to_dict() == {"object_type": "source_artifact", "object_id": "sha256:abc"}
    assert ActionStatus.COMMITTED.is_success is True
    assert ActionStatus.FAILED.is_success is False
