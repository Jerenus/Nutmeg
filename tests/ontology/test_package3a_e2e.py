from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.bundle_actions import BundleActions, FreezeBundleRequest
from nutmeg.ontology.actions.forecast_actions import (
    CommitForecastRequest,
    FactorInput,
    ForecastActions,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.evidence.models import VerificationMethod
from nutmeg.ontology.repository.evidence import ObservationRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel


def _commit(match, belief, factors, key, role=ActorRole.JUDGE_OPERATOR, bundle=None):
    return CommitForecastRequest(
        match_id=match, market_definition_id="md-had", decision_session_id=None,
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, belief_distribution=belief,
        factors=factors, commitment_tier="commit", evidence_bundle_id=bundle,
        prior_snapshot_id=None, falsifier=None, actor_id="op:owner", actor_role=role,
        idempotency_key=key, requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC))


def test_belief_layer_end_to_end(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        for oid, recorded in (("obs-early", "2026-07-19T14:00:00+08:00"),
                              ("obs-late", "2026-07-19T16:00:00+08:00")):
            uow.evidence.insert_observation(ObservationRow(
                observation_id=oid, observation_type="availability", subject_type="person",
                subject_id="p", scope_match_id="match-1", value={"availability": "out"},
                schema_version="1", valid_from="2026-07-19T00:00:00+08:00", valid_to=None,
                observed_at=recorded, recorded_at=recorded,
                verification_method=VerificationMethod.OFFICIAL.value, quality={}))

    # (b) freeze excludes evidence recorded after cutoff
    bundle = BundleActions(service).freeze_bundle(FreezeBundleRequest(
        match_id="match-1", decision_session_id=None, cutoff_at="2026-07-19T15:00:00+08:00",
        market_snapshot_id=None, prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        candidate_observation_ids=["obs-early", "obs-late"], caveat_claim_ids=[],
        actor_id="system:freeze", actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="b:1",
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    bundle_id = bundle.result_refs[0].object_id
    with OntologyUnitOfWork(kernel.engine) as uow:
        items = uow.decision.bundle_item_ids(bundle_id)
        assert "obs-early" in items and "obs-late" not in items

    forecasts = ForecastActions(service)
    # (a) committed forecast whose factor deltas reconstruct belief - prior
    committed = forecasts.commit_forecast(_commit(
        "match-1", {"home": 0.6, "draw": 0.25, "away": 0.15},
        [FactorInput("fd-rest", {"home": 0.1, "draw": -0.05, "away": -0.05}, [], [], "rest")],
        "c:1", bundle=bundle_id))
    assert committed.status is ActionStatus.COMMITTED

    # (c) a second commit keeps exactly one current committed and supersedes the first
    forecasts.commit_forecast(_commit(
        "match-1", {"home": 0.55, "draw": 0.28, "away": 0.17}, [], "c:2"))
    with OntologyUnitOfWork(kernel.engine) as uow:
        series = uow.decision.ensure_series("match-1", "md-had")
        assert uow.decision.count_committed_revisions() == 1
        assert uow.decision.current_committed_revision(series).supersedes_revision_id is not None

    # (d) an ai_analyst cannot commit
    denied = forecasts.commit_forecast(_commit(
        "match-1", {"home": 0.5, "draw": 0.3, "away": 0.2}, [], "c:ai", ActorRole.AI_ANALYST))
    assert denied.status is ActionStatus.REJECTED

    status = kernel.status()
    assert status.forecast_count == 1
    assert status.bundle_count == 1
