"""Canonical command-bound HMAC snapshot tokens for the operator surface."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nutmeg.ontology.actions.models import canonical_json

_FRAME = re.compile(r'[A-Za-z0-9_-]+')
_CONTEXT = b'operator-snapshot-v1\0'


class OperatorCommandKind(StrEnum):
    FREEZE_EVIDENCE = 'freeze_evidence'
    RECORD_BASELINE_ENVELOPE = 'record_baseline_envelope'
    COMMIT_MATCH_JUDGMENT = 'commit_match_judgment'
    FREEZE_JUDGMENT_PRESCRIPTION = 'freeze_judgment_prescription'
    REQUEST_CANDIDATE_GENERATION = 'request_candidate_generation'
    SELECT_CANDIDATE = 'select_candidate'
    RECORD_NO_TICKET = 'record_no_ticket'
    SUPERSEDE_NO_TICKET = 'supersede_no_ticket'
    CREATE_TICKET_BATCH = 'create_ticket_batch'
    ADJUDICATE_AUDIT_WARN = 'adjudicate_audit_warn'
    APPROVE_TICKET_BATCH = 'approve_ticket_batch'
    REQUEST_CONFIRMATION = 'request_confirmation'
    REQUEST_SETTLEMENT = 'request_settlement'
    GRADE_PREDICTION = 'grade_prediction'
    RECORD_SCOREBOARD_EFFECT_DISPOSITION = 'record_scoreboard_effect_disposition'
    RECORD_SCOREBOARD_OBSERVATION = 'record_scoreboard_observation'
    REQUEST_SCOREBOARD_REVIEW_COMPLETION = 'request_scoreboard_review_completion'
    REBUILD_SCOREBOARD_PROJECTION = 'rebuild_scoreboard_projection'


class OperatorSnapshotTokenPayloadV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    task_snapshot_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    work_item_id: str = Field(min_length=1, max_length=500)
    command_kind: OperatorCommandKind
    dependency_revision_ids: list[str] = Field(max_length=500)

    @field_validator('dependency_revision_ids')
    @classmethod
    def _dependencies_are_a_sorted_set(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 500 for item in value):
            raise ValueError('dependency revision IDs must be non-empty and bounded')
        if value != sorted(set(value)):
            raise ValueError('dependency revision IDs must be sorted and unique')
        return value


class OperatorSnapshotTokenError(ValueError):
    """Opaque token error whose message never includes token material."""

    def __init__(self, code: str) -> None:
        message = (
            'operator task changed; refresh before retrying'
            if code == 'task_snapshot_changed'
            else 'invalid operator request'
        )
        super().__init__(message)
        self.code = code


class OperatorSnapshotTokenCodec:
    def __init__(self, signing_key: bytes | str) -> None:
        key = signing_key.encode('utf-8') if isinstance(signing_key, str) else signing_key
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError('operator token signing key must contain at least 32 bytes')
        self._key = key

    def __repr__(self) -> str:
        return 'OperatorSnapshotTokenCodec(<redacted>)'

    @staticmethod
    def _encode_frame(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')

    @staticmethod
    def _decode_frame(value: str) -> bytes:
        if _FRAME.fullmatch(value) is None:
            raise OperatorSnapshotTokenError('invalid_request')
        padding = '=' * ((4 - len(value) % 4) % 4)
        try:
            decoded = base64.b64decode(
                value + padding,
                altchars=b'-_',
                validate=True,
            )
        except (ValueError, binascii.Error) as error:
            raise OperatorSnapshotTokenError('invalid_request') from error
        if OperatorSnapshotTokenCodec._encode_frame(decoded) != value:
            raise OperatorSnapshotTokenError('invalid_request')
        return decoded

    def encode(self, payload: OperatorSnapshotTokenPayloadV1) -> str:
        if not isinstance(payload, OperatorSnapshotTokenPayloadV1):
            raise TypeError('payload must be OperatorSnapshotTokenPayloadV1')
        payload_bytes = canonical_json(payload.model_dump(mode='json')).encode('utf-8')
        signature = hmac.new(self._key, _CONTEXT + payload_bytes, hashlib.sha256).digest()
        return f'{self._encode_frame(payload_bytes)}.{self._encode_frame(signature)}'

    def decode(self, token: str) -> OperatorSnapshotTokenPayloadV1:
        if not isinstance(token, str) or token.count('.') != 1:
            raise OperatorSnapshotTokenError('invalid_request')
        payload_frame, signature_frame = token.split('.')
        payload_bytes = self._decode_frame(payload_frame)
        signature = self._decode_frame(signature_frame)
        expected = hmac.new(self._key, _CONTEXT + payload_bytes, hashlib.sha256).digest()
        if len(signature) != hashlib.sha256().digest_size or not hmac.compare_digest(
            signature, expected
        ):
            raise OperatorSnapshotTokenError('invalid_request')
        try:
            document = json.loads(payload_bytes.decode('utf-8'))
            payload = OperatorSnapshotTokenPayloadV1.model_validate(document)
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise OperatorSnapshotTokenError('invalid_request') from error
        canonical_bytes = canonical_json(payload.model_dump(mode='json')).encode('utf-8')
        if canonical_bytes != payload_bytes or self._encode_frame(canonical_bytes) != payload_frame:
            raise OperatorSnapshotTokenError('invalid_request')
        return payload

    def verify(
        self,
        token: str,
        *,
        expected_command_kind: OperatorCommandKind,
        current_task_snapshot_hash: str,
        current_work_item_id: str,
        current_dependency_revision_ids: Sequence[str],
    ) -> OperatorSnapshotTokenPayloadV1:
        payload = self.decode(token)
        if payload.command_kind is not expected_command_kind:
            raise OperatorSnapshotTokenError('invalid_request')
        current_dependencies = list(current_dependency_revision_ids)
        if (
            payload.task_snapshot_hash != current_task_snapshot_hash
            or payload.work_item_id != current_work_item_id
            or payload.dependency_revision_ids != current_dependencies
        ):
            raise OperatorSnapshotTokenError('task_snapshot_changed')
        return payload


__all__ = [
    'OperatorCommandKind',
    'OperatorSnapshotTokenCodec',
    'OperatorSnapshotTokenError',
    'OperatorSnapshotTokenPayloadV1',
]
