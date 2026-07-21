from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SHARP = {"home": 0.72, "draw": 0.18, "away": 0.10}


def _seed(kernel):
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    svc = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id=None,
        prior_distribution=PRIOR, belief_distribution=SHARP, factors=[], commitment_tier="commit",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="c:1", requested_at=T))
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.finance.insert_outcome(OutcomeRow(
            outcome_id="mo-1", match_id="match-1", version=1, score_90="2-0", score_aet=None,
            penalties=None, status="final", source_artifact_retrieval_ids=[],
            recorded_at=T.isoformat(), supersedes_outcome_id=None))
        uow.market.insert_snapshot(SnapshotRow(
            market_snapshot_id="ms-1", match_id="match-1", market_definition_id="md-had",
            snapshot_kind="closing", as_of=T.isoformat(),
            fair_distribution={"home": 0.74, "draw": 0.17, "away": 0.09},
            devig_method="proportional", method_version="v1", source_coverage={}, freshness={},
            disagreement={}))


def test_calibrate_builds_scorecards_and_is_deterministic(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    _seed(kernel)
    request = CalibrateRequest(as_of=T.isoformat(), built_at="2026-07-20T00:00:00+00:00")
    first = kernel.calibrate.build(request)
    assert first.status == "succeeded"
    assert set(first.scorecards) == {"forecast_truth", "market_information", "calibration"}
    status = kernel.status()
    assert status.scorecard_count >= 3 and status.projection_run_count >= 1

    second = kernel.calibrate.build(request)   # same high-watermark -> deterministic
    assert second.scorecard_count == first.scorecard_count
