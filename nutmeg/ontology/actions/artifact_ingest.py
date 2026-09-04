"""``IngestArtifact`` — the single production Action handler in Package 1.

It proves the whole write boundary end to end: permission is checked before the
handler runs (so a denied actor writes neither the database nor a blob),
idempotency replays a committed retrieval instead of duplicating it, and the CAS
blob plus its SourceArtifact and ArtifactRetrieval rows are recorded atomically.
The Action payload carries the content hash and metadata only — never the raw
bytes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.ontology.actions.models import (
    ActionCommand,
    ActionOutcome,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.service import ActionBatchItem, ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.repository.artifacts import ArtifactRetrievalRow

_RETRIEVAL_STATUS_STORED = 'stored'


@dataclass(frozen=True, slots=True)
class ArtifactIngestRequest:
    content: bytes
    content_type: str
    source_name: str
    source_type: str
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    retrieved_at: datetime
    requested_url: str | None = None
    source_run_id: str | None = None
    canonical_url: str | None = None
    published_at: str | None = None

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError('retrieved_at must be timezone-aware')
        if not self.content:
            raise ValueError('content must be non-empty')
        for name in ('content_type', 'source_name', 'source_type', 'actor_id'):
            if not getattr(self, name).strip():
                raise ValueError(f'{name} is required')
        if not self.idempotency_key.strip():
            raise ValueError('idempotency_key is required')


class ArtifactIngestService:
    def __init__(
        self,
        *,
        action_service: ActionService,
        artifact_store: ContentAddressedArtifactStore,
    ) -> None:
        self._action_service = action_service
        self._artifact_store = artifact_store

    def ingest(self, request: ArtifactIngestRequest) -> ActionOutcome:
        command, handler = self.prepare(request)
        return self._action_service.execute(command, handler)

    def prepare(
        self,
        request: ArtifactIngestRequest,
        *,
        action_id: str | None = None,
        payload_extension: dict[str, object] | None = None,
    ) -> ActionBatchItem:
        """Build an artifact operation for a caller-owned atomic batch."""
        digest = hashlib.sha256(request.content).hexdigest()
        artifact_id = f'sha256:{digest}'
        byte_size = len(request.content)
        retrieval_id = 'RET-' + hashlib.sha256(
            request.idempotency_key.encode('utf-8')
        ).hexdigest()[:32]
        retrieved_at_iso = request.retrieved_at.astimezone(UTC).isoformat()

        payload: dict[str, object] = {
            'artifact_id': artifact_id,
            'content_hash': digest,
            'byte_size': byte_size,
            'content_type': request.content_type,
            'source_name': request.source_name,
            'source_type': request.source_type,
            'source_run_id': request.source_run_id,
            'retrieval_id': retrieval_id,
            'retrieved_at': retrieved_at_iso,
            'requested_url': request.requested_url,
            'canonical_url': request.canonical_url,
            'published_at': request.published_at,
        }
        if payload_extension:
            overlap = payload.keys() & payload_extension.keys()
            if overlap:
                raise ValueError(
                    'artifact payload extension conflicts with reserved fields: '
                    f'{sorted(overlap)}'
                )
            payload.update(payload_extension)
        command = ActionCommand.create(
            action_type='ingest_artifact',
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            idempotency_key=request.idempotency_key,
            payload=payload,
            requested_at=request.retrieved_at,
            action_id=action_id,
        )

        def handler(uow, _command) -> tuple[ObjectRef, ...]:
            blob = self._artifact_store.put_bytes(request.content)
            uow.artifacts.upsert_blob(
                blob,
                request.content_type,
                datetime.now(UTC).isoformat(),
            )
            uow.artifacts.insert_retrieval(
                ArtifactRetrievalRow(
                    artifact_retrieval_id=retrieval_id,
                    artifact_id=blob.artifact_id,
                    source_run_id=request.source_run_id,
                    source_name=request.source_name,
                    source_type=request.source_type,
                    reported_content_type=request.content_type,
                    canonical_url=request.canonical_url,
                    requested_url=request.requested_url,
                    published_at=request.published_at,
                    retrieved_at=retrieved_at_iso,
                    status=_RETRIEVAL_STATUS_STORED,
                )
            )
            return (
                ObjectRef('source_artifact', blob.artifact_id),
                ObjectRef('artifact_retrieval', retrieval_id),
            )

        return command, handler

    def execute_batch(
        self, items: tuple[ActionBatchItem, ...]
    ) -> tuple[ActionOutcome, ...]:
        """Commit a prepared artifact and its related Actions atomically."""
        return self._action_service.execute_batch(items)
