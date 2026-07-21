from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest, ArtifactIngestService
from nutmeg.ontology.actions.claim_actions import (
    ClaimActions,
    ClaimAdjudicationRequest,
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


def _claim(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    ingest = ArtifactIngestService(
        action_service=service,
        artifact_store=ContentAddressedArtifactStore(tmp_path / "artifacts"))
    art = ingest.ingest(ArtifactIngestRequest(
        content=b"statement", content_type="text/plain", source_name="s", source_type="web",
        actor_id="source:s", actor_role=ActorRole.CONNECTOR, idempotency_key="a:1",
        retrieved_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    actions = ClaimActions(service)
    claim_id = actions.extract_claim(ExtractClaimRequest(
        subject_type="person", subject_id="p", predicate="availability",
        value={"availability": "out"}, scope_match_id=None, valid_from="2026-07-19T00:00:00+08:00",
        extractor="x", extractor_version="1",
        spans=[EvidenceSpanInput(
            art.result_refs[0].object_id, art.result_refs[1].object_id, "q", None)],
        actor_id="model:x", actor_role=ActorRole.AI_EXTRACTOR, idempotency_key="c:1",
        requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC))).result_refs[0].object_id
    return actions, engine, claim_id


def _adj(claim_id: str, key: str, role: ActorRole) -> ClaimAdjudicationRequest:
    return ClaimAdjudicationRequest(
        claim_id=claim_id, actor_id="op:owner", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC))


def test_verify_records_status_event_and_current_status(tmp_path: Path) -> None:
    actions, engine, claim_id = _claim(tmp_path)
    outcome = actions.verify_claim(_adj(claim_id, "v:1", ActorRole.JUDGE_OPERATOR))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.evidence.claim_status(claim_id) == ClaimStatus.VERIFIED.value
        assert uow.evidence.claim_status_history(claim_id)[-1] == ("provisional", "verified")


def test_ai_extractor_cannot_verify_its_own_claim(tmp_path: Path) -> None:
    actions, _engine, claim_id = _claim(tmp_path)
    outcome = actions.verify_claim(_adj(claim_id, "v:denied", ActorRole.AI_EXTRACTOR))
    assert outcome.status is ActionStatus.REJECTED
