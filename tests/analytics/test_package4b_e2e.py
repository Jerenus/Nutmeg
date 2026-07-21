from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.factor_actions import ApplyFactorStatusRequest, FactorActions
from nutmeg.ontology.actions.forecast_actions import (
    CommitForecastRequest,
    FactorInput,
    ForecastActions,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.decision import FactorDefinitionRow, FactorFamilyRow
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.storage.duckdb_utils import connect_analytics_db

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SHARP = {"home": 0.65, "draw": 0.2, "away": 0.15}


def _seed(kernel):
    svc = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.decision.insert_factor_family(FactorFamilyRow("ff-rest", "rest", None))
        uow.decision.insert_factor_definition(FactorDefinitionRow(
            factor_definition_id="fd-good", factor_family_id="ff-rest", version=1, name="rest",
            definition=None, scope=None, status="probation", born_from_refs=[],
            valid_from=T.isoformat(), valid_to=None, policy_version="governance-v1"))
    for i in range(3):
        match = f"m-{i}"
        with OntologyUnitOfWork(kernel.engine) as uow:
            uow.identity.insert_match_minimal(match)
        ForecastActions(svc).commit_forecast(CommitForecastRequest(
            match_id=match, market_definition_id="md-had", decision_session_id=None,
            prior_distribution=PRIOR, belief_distribution=SHARP,
            factors=[FactorInput("fd-good", {"home": 0.15, "draw": -0.1, "away": -0.05}, [], [],
                                 None)],
            commitment_tier="commit", evidence_bundle_id=None, prior_snapshot_id=None,
            falsifier=None, actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"c:{i}", requested_at=T))
        with OntologyUnitOfWork(kernel.engine) as uow:
            uow.finance.insert_outcome(OutcomeRow(
                outcome_id=f"mo-{i}", match_id=match, version=1, score_90="2-0", score_aet=None,
                penalties=None, status="final", source_artifact_retrieval_ids=[],
                recorded_at=T.isoformat(), supersedes_outcome_id=None))
            uow.market.insert_snapshot(SnapshotRow(
                market_snapshot_id=f"ms-{i}", match_id=match, market_definition_id="md-had",
                snapshot_kind="closing", as_of=T.isoformat(),
                fair_distribution={"home": 0.66, "draw": 0.19, "away": 0.15},
                devig_method="proportional", method_version="v1", source_coverage={}, freshness={},
                disagreement={}))
    return svc


def test_package4b_learning_end_to_end(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    svc = _seed(kernel)
    request = CalibrateRequest(as_of=T.isoformat(), built_at="2026-07-20T00:00:00+00:00")
    first = kernel.calibrate.build(request)
    second = kernel.calibrate.build(request)   # deterministic at the same high-watermark
    assert first.status == "succeeded"
    assert first.factor_estimate_count == second.factor_estimate_count

    analytics = kernel._paths.analytics
    with connect_analytics_db(analytics) as con:
        proposals = con.execute(
            "SELECT from_status, to_status FROM factor_lifecycle_proposals "
            "WHERE factor_definition_id='fd-good'").fetchall()
        regimes = con.execute("SELECT count(*) FROM regime_vectors").fetchone()[0]
    assert proposals == [("probation", "active")]   # proposed, not applied
    assert regimes == 3

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.decision.factor_status("fd-good") == "probation"   # calibrate changed nothing

    applied = FactorActions(svc).apply_factor_status(ApplyFactorStatusRequest(
        factor_definition_id="fd-good", target_status="active", actor_id="op",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="ap:1", requested_at=T))
    assert applied.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.decision.factor_status("fd-good") == "active"

    status = kernel.status()
    assert status.factor_estimate_count >= 1
    assert status.regime_vector_count == 3
    assert status.lifecycle_proposal_count >= 1
