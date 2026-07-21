from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.bundle_actions import BundleActions, FreezeBundleRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import VerificationMethod
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        for oid, recorded in (("obs-early", "2026-07-19T14:00:00+08:00"),
                              ("obs-late", "2026-07-19T16:00:00+08:00")):
            uow.evidence.insert_observation(ObservationRow(
                observation_id=oid, observation_type="availability", subject_type="person",
                subject_id="p", scope_match_id="match-1", value={"availability": "out"},
                schema_version="1", valid_from="2026-07-19T00:00:00+08:00", valid_to=None,
                observed_at=recorded, recorded_at=recorded,
                verification_method=VerificationMethod.OFFICIAL.value, quality={}))
    return BundleActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM) -> FreezeBundleRequest:
    return FreezeBundleRequest(
        match_id="match-1", decision_session_id="sess-x", cutoff_at="2026-07-19T15:00:00+08:00",
        market_snapshot_id=None, prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        candidate_observation_ids=["obs-early", "obs-late"], caveat_claim_ids=[],
        actor_id="system:freeze", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC))


def test_freeze_excludes_evidence_recorded_after_cutoff(tmp_path: Path) -> None:
    actions, engine = _setup(tmp_path)
    outcome = actions.freeze_bundle(_req("b:1"))
    assert outcome.status is ActionStatus.COMMITTED
    bundle_id = outcome.result_refs[0].object_id
    with OntologyUnitOfWork(engine) as uow:
        items = uow.decision.bundle_item_ids(bundle_id)
        assert "obs-early" in items          # recorded 14:00 <= cutoff 15:00
        assert "obs-late" not in items       # recorded 16:00 > cutoff — no future leak


def test_ai_analyst_cannot_freeze_bundle(tmp_path: Path) -> None:
    actions, _engine = _setup(tmp_path)
    assert actions.freeze_bundle(_req("b:d", ActorRole.AI_ANALYST)).status is ActionStatus.REJECTED
