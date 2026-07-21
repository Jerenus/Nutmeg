from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.storage.duckdb_utils import connect_analytics_db

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SHARP = {"home": 0.75, "draw": 0.15, "away": 0.10}


def _commit(svc, match, belief, key):
    ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id=match, market_definition_id="md-had", decision_session_id=None,
        prior_distribution=PRIOR, belief_distribution=belief, factors=[], commitment_tier="commit",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key, requested_at=T))


def _outcome_and_closing(uow, match, oid, sid):
    uow.finance.insert_outcome(OutcomeRow(
        outcome_id=oid, match_id=match, version=1, score_90="2-0", score_aet=None, penalties=None,
        status="final", source_artifact_retrieval_ids=[], recorded_at=T.isoformat(),
        supersedes_outcome_id=None))
    uow.market.insert_snapshot(SnapshotRow(
        market_snapshot_id=sid, match_id=match, market_definition_id="md-had",
        snapshot_kind="closing", as_of=T.isoformat(),
        fair_distribution={"home": 0.74, "draw": 0.17, "away": 0.09}, devig_method="proportional",
        method_version="v1", source_coverage={}, freshness={}, disagreement={}))


def test_package4a_calibrate_end_to_end(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    for match in ("match-sharp", "match-follow", "match-open"):
        with OntologyUnitOfWork(kernel.engine) as uow:
            uow.identity.insert_match_minimal(match)
    _commit(ActionService(lambda: OntologyUnitOfWork(kernel.engine)), "match-sharp", SHARP, "c:s")
    svc = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    _commit(svc, "match-follow", PRIOR, "c:f")   # follow-market
    _commit(svc, "match-open", SHARP, "c:o")     # never gets an outcome
    with OntologyUnitOfWork(kernel.engine) as uow:
        _outcome_and_closing(uow, "match-sharp", "mo-s", "ms-s")
        _outcome_and_closing(uow, "match-follow", "mo-f", "ms-f")

    request = CalibrateRequest(as_of=T.isoformat(), built_at="2026-07-20T00:00:00+00:00")
    first = kernel.calibrate.build(request)
    second = kernel.calibrate.build(request)   # same high-watermark -> deterministic

    analytics = OntologyPaths.from_data_dir(tmp_path / "data").analytics
    with connect_analytics_db(analytics) as con:
        score_rows = con.execute("SELECT count(*) FROM forecast_scores").fetchone()[0]
        scored = con.execute(
            "SELECT count(*) FROM forecast_scores WHERE has_outcome").fetchone()[0]
        truth_skill = con.execute(
            "SELECT brier_skill FROM forecast_scorecards WHERE scorecard='forecast_truth'"
        ).fetchone()[0]
    assert score_rows == 3 and scored == 2          # match-open scored as has_outcome=False, not 0
    assert truth_skill > 0                           # sharper belief beats the market prior
    assert first.scorecard_count == second.scorecard_count   # determinism
    status = kernel.status()
    assert status.scorecard_count >= 3 and status.projection_run_count >= 2
