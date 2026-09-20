"""Immutable Action value objects and canonical request hashing.

Every formal write to the kernel is an Action. The command envelope is content-
addressed by a canonical request hash over the *semantic* request (action type,
actor identity/role, expected versions, payload, policy version) — deliberately
excluding the generated action id, the wall-clock request time and the
idempotency key — so the same logical request always hashes the same, and a
reused idempotency key carrying a different request can be detected as a
conflict.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

DEFAULT_POLICY_VERSION = 'governance-v1'


class ActorRole(StrEnum):
    CONNECTOR = 'connector'
    AI_EXTRACTOR = 'ai_extractor'
    AI_ANALYST = 'ai_analyst'
    JUDGE_OPERATOR = 'judge_operator'
    DETERMINISTIC_SYSTEM = 'deterministic_system'
    REPLAY_ADJUDICATOR = 'replay_adjudicator'


class ActionStatus(StrEnum):
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    COMMITTED = 'committed'
    FAILED = 'failed'

    @property
    def is_success(self) -> bool:
        return self is ActionStatus.COMMITTED


def canonical_json(document: object) -> str:
    """Deterministic JSON: sorted keys, compact separators, UTF-8, unicode kept."""
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class ObjectRef:
    object_type: str
    object_id: str

    def to_dict(self) -> dict[str, str]:
        return {'object_type': self.object_type, 'object_id': self.object_id}


@dataclass(frozen=True, slots=True)
class ActionCommand:
    action_id: str
    action_type: str
    actor_id: str
    actor_role: ActorRole
    requested_at: str
    idempotency_key: str
    payload: dict[str, object]
    expected_versions: dict[str, int]
    policy_version: str
    historical_replay: bool
    replay_run_id: str | None
    request_hash: str

    @classmethod
    def create(
        cls,
        *,
        action_type: str,
        actor_id: str,
        actor_role: ActorRole,
        idempotency_key: str,
        payload: dict[str, object],
        requested_at: datetime,
        expected_versions: dict[str, int] | None = None,
        policy_version: str = DEFAULT_POLICY_VERSION,
        action_id: str | None = None,
        historical_replay: bool = False,
        replay_run_id: str | None = None,
    ) -> ActionCommand:
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError('requested_at must be timezone-aware')
        if not idempotency_key or not idempotency_key.strip():
            raise ValueError('idempotency_key is required')
        if historical_replay != (replay_run_id is not None):
            raise ValueError('replay provenance fields must be paired')

        normalized_versions: dict[str, int] = {}
        for key, value in (expected_versions or {}).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('expected version must be a non-negative integer')
            normalized_versions[str(key)] = int(value)

        normalized_payload = copy.deepcopy(payload)
        request_material = {
            'action_type': action_type,
            'actor_id': actor_id,
            'actor_role': actor_role.value,
            'expected_versions': normalized_versions,
            'payload': normalized_payload,
            'policy_version': policy_version,
            'historical_replay': historical_replay,
            'replay_run_id': replay_run_id,
        }
        request_hash = hashlib.sha256(
            canonical_json(request_material).encode('utf-8')
        ).hexdigest()

        return cls(
            action_id=action_id or f'ACT-{uuid4().hex}',
            action_type=action_type,
            actor_id=actor_id,
            actor_role=actor_role,
            requested_at=requested_at.astimezone(UTC).isoformat(),
            idempotency_key=idempotency_key,
            payload=normalized_payload,
            expected_versions=normalized_versions,
            policy_version=policy_version,
            historical_replay=historical_replay,
            replay_run_id=replay_run_id,
            request_hash=request_hash,
        )


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action_id: str
    action_type: str
    status: ActionStatus
    result_refs: tuple[ObjectRef, ...] = field(default_factory=tuple)
    error_code: str | None = None
    error_detail: str | None = None
    committed_at: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status.is_success
