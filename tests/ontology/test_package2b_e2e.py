from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.claim_actions import (
    ClaimActions,
    ClaimAdjudicationRequest,
    EvidenceSpanInput,
    ExtractClaimRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel


def test_conflicting_claims_coexist_and_ai_cannot_verify(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    claims = ClaimActions(service)

    def _art(text: str, key: str):
        outcome = kernel.artifact_ingest.ingest(ArtifactIngestRequest(
            content=text.encode(), content_type="text/plain", source_name="s", source_type="web",
            actor_id="source:s", actor_role=ActorRole.CONNECTOR, idempotency_key=key,
            retrieved_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
        return outcome.result_refs[0].object_id, outcome.result_refs[1].object_id

    def _extract(value, key, art_key, text):
        aid, rid = _art(text, art_key)
        return claims.extract_claim(ExtractClaimRequest(
            subject_type="person", subject_id="p", predicate="availability", value=value,
            scope_match_id=None, valid_from="2026-07-19T00:00:00+08:00", extractor="nlp",
            extractor_version="1",
            spans=[EvidenceSpanInput(aid, rid, text, None)],
            actor_id="model:x", actor_role=ActorRole.AI_EXTRACTOR, idempotency_key=key,
            requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC))).result_refs[0].object_id

    c_out = _extract({"availability": "out"}, "c:out", "a:out", "OUT injured")
    _extract({"availability": "available"}, "c:fit", "a:fit", "fit to play")

    with OntologyUnitOfWork(kernel.engine) as uow:
        # both provisional claims coexist — no auto-overwrite
        assert len(uow.evidence.claims_for("person", "p")) == 2

    # AI cannot verify its own claim
    denied = claims.verify_claim(ClaimAdjudicationRequest(
        claim_id=c_out, actor_id="model:x", actor_role=ActorRole.AI_EXTRACTOR,
        idempotency_key="v:denied", requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC)))
    assert denied.status is ActionStatus.REJECTED

    # operator verifies one; status trail is replayable, the other is untouched
    ok = claims.verify_claim(ClaimAdjudicationRequest(
        claim_id=c_out, actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="v:ok", requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC)))
    assert ok.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.evidence.claim_status(c_out) == "verified"
        assert uow.evidence.claim_status_history(c_out) == [
            (None, "provisional"), ("provisional", "verified"),
        ]
        assert kernel.status().claim_count == 2
