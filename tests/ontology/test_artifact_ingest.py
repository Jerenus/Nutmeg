from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, func, select

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest, ArtifactIngestService
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.schema import artifact_retrievals, source_artifacts
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _count(connection: Connection, table) -> int:
    return connection.execute(select(func.count()).select_from(table)).scalar_one()


def _ingest_service(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    actions = ActionService(lambda: OntologyUnitOfWork(engine))
    return ArtifactIngestService(
        action_service=actions,
        artifact_store=ContentAddressedArtifactStore(tmp_path / "artifacts"),
    ), engine


def _request(key: str, role: ActorRole = ActorRole.CONNECTOR) -> ArtifactIngestRequest:
    return ArtifactIngestRequest(
        content=b'{"match":"A-B"}',
        content_type="application/json",
        source_name="sporttery",
        source_type="api",
        actor_id="source:sporttery",
        actor_role=role,
        idempotency_key=key,
        retrieved_at=datetime(2026, 7, 21, 8, tzinfo=UTC),
        requested_url="https://example.test/odds",
    )


def test_ingest_is_idempotent_and_keeps_one_blob_and_retrieval(tmp_path: Path) -> None:
    service, engine = _ingest_service(tmp_path)
    first = service.ingest(_request("sporttery:one"))
    second = service.ingest(_request("sporttery:one"))
    assert first.status is ActionStatus.COMMITTED
    assert second.action_id == first.action_id
    with engine.connect() as connection:
        assert _count(connection, source_artifacts) == 1
        assert _count(connection, artifact_retrievals) == 1


def test_same_content_from_two_retrievals_reuses_artifact(tmp_path: Path) -> None:
    service, engine = _ingest_service(tmp_path)
    service.ingest(_request("sporttery:one"))
    service.ingest(_request("sporttery:two"))
    with engine.connect() as connection:
        assert _count(connection, source_artifacts) == 1
        assert _count(connection, artifact_retrievals) == 2


def test_unauthorized_ingest_writes_neither_db_nor_blob(tmp_path: Path) -> None:
    service, engine = _ingest_service(tmp_path)
    outcome = service.ingest(_request("model:denied", ActorRole.AI_ANALYST))
    assert outcome.status is ActionStatus.REJECTED
    with engine.connect() as connection:
        assert _count(connection, source_artifacts) == 0
    assert not any((tmp_path / "artifacts").rglob("*"))
