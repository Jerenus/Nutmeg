"""SourceArtifact and ArtifactRetrieval persistence.

One immutable ``SourceArtifact`` per content hash; many ``ArtifactRetrieval``
rows pointing at it — the same bytes fetched twice add a retrieval, never a
second blob row. Metadata for an existing artifact must match exactly; a
disagreement is a bug, not an update.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.artifacts import ArtifactBlob
from nutmeg.ontology.errors import OntologyError
from nutmeg.ontology.repository import schema


@dataclass(frozen=True, slots=True)
class ArtifactRetrievalRow:
    artifact_retrieval_id: str
    artifact_id: str
    source_run_id: str | None
    source_name: str
    source_type: str
    reported_content_type: str
    canonical_url: str | None
    requested_url: str | None
    published_at: str | None
    retrieved_at: str
    status: str


class ArtifactRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def upsert_blob(
        self,
        blob: ArtifactBlob,
        content_type: str,
        first_recorded_at: str,
    ) -> None:
        storage_path = str(blob.relative_path)
        existing = (
            self._connection.execute(
                select(schema.source_artifacts).where(
                    schema.source_artifacts.c.artifact_id == blob.artifact_id
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            if (
                existing['content_hash'] != blob.content_hash
                or existing['byte_size'] != blob.byte_size
                or existing['storage_path'] != storage_path
            ):
                raise OntologyError(
                    f'artifact metadata disagreement for {blob.artifact_id}'
                )
            # Retain the first canonical content_type; retrievals carry their own.
            return
        self._connection.execute(
            insert(schema.source_artifacts).values(
                artifact_id=blob.artifact_id,
                first_recorded_at=first_recorded_at,
                content_type=content_type,
                storage_path=storage_path,
                byte_size=blob.byte_size,
                content_hash=blob.content_hash,
            )
        )

    def insert_retrieval(self, retrieval: ArtifactRetrievalRow) -> None:
        self._connection.execute(
            insert(schema.artifact_retrievals).values(
                artifact_retrieval_id=retrieval.artifact_retrieval_id,
                artifact_id=retrieval.artifact_id,
                source_run_id=retrieval.source_run_id,
                source_name=retrieval.source_name,
                source_type=retrieval.source_type,
                reported_content_type=retrieval.reported_content_type,
                canonical_url=retrieval.canonical_url,
                requested_url=retrieval.requested_url,
                published_at=retrieval.published_at,
                retrieved_at=retrieval.retrieved_at,
                status=retrieval.status,
            )
        )

    def count_artifacts(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(schema.source_artifacts)
        ).scalar_one()

    def count_retrievals(self) -> int:
        return self._connection.execute(
            select(func.count()).select_from(schema.artifact_retrievals)
        ).scalar_one()
