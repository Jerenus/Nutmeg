from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest, ArtifactIngestService
from nutmeg.ontology.actions.claim_actions import (
    ClaimActions,
    EvidenceSpanInput,
    ExtractClaimRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
from nutmeg.ontology.evidence.models import ClaimStatus
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    ingest = ArtifactIngestService(
        action_service=service, artifact_store=ContentAddressedArtifactStore(tmp_path / "artifacts")
    )
    ingested = ingest.ingest(ArtifactIngestRequest(
        content=b"club statement: striker OUT with injury", content_type="text/plain",
        source_name="club-site", source_type="web", actor_id="source:club",
        actor_role=ActorRole.CONNECTOR, idempotency_key="art:1",
        retrieved_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    artifact_id = ingested.result_refs[0].object_id
    retrieval_id = ingested.result_refs[1].object_id
    return ClaimActions(service), engine, artifact_id, retrieval_id


def test_extract_claim_is_provisional_with_span(tmp_path: Path) -> None:
    actions, engine, artifact_id, retrieval_id = _setup(tmp_path)
    outcome = actions.extract_claim(ExtractClaimRequest(
        subject_type="person", subject_id="person-striker", predicate="availability",
        value={"availability": "out"}, scope_match_id="match-1",
        valid_from="2026-07-19T00:00:00+08:00", extractor="news-nlp", extractor_version="1",
        spans=[EvidenceSpanInput(artifact_id=artifact_id, artifact_retrieval_id=retrieval_id,
                                 quote="striker OUT with injury", locator="p1")],
        actor_id="model:extractor", actor_role=ActorRole.AI_EXTRACTOR, idempotency_key="claim:1",
        requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.COMMITTED
    claim_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        assert uow.evidence.claim_status(claim_id) == ClaimStatus.PROVISIONAL.value
        assert len(uow.evidence.claims_for("person", "person-striker")) == 1


def test_connector_cannot_extract_claim(tmp_path: Path) -> None:
    actions, _engine, artifact_id, retrieval_id = _setup(tmp_path)
    outcome = actions.extract_claim(ExtractClaimRequest(
        subject_type="person", subject_id="p", predicate="availability", value={},
        scope_match_id=None, valid_from="2026-07-19T00:00:00+08:00", extractor="x",
        extractor_version="1",
        spans=[EvidenceSpanInput(artifact_id=artifact_id, artifact_retrieval_id=retrieval_id,
                                 quote="q", locator=None)],
        actor_id="source:club", actor_role=ActorRole.CONNECTOR, idempotency_key="claim:denied",
        requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.REJECTED
