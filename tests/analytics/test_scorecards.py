import json
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.scorecards import compute_scorecard_rows
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SHARP = {"home": 0.75, "draw": 0.15, "away": 0.10}


def test_three_scorecards_with_positive_skill(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    for i in (1, 2):
        match = f"match-{i}"
        with OntologyUnitOfWork(engine) as uow:
            uow.identity.insert_match_minimal(match)
        ForecastActions(svc).commit_forecast(CommitForecastRequest(
            match_id=match, market_definition_id="md-had", decision_session_id=None,
            prior_distribution=PRIOR, belief_distribution=SHARP, factors=[],
            commitment_tier="commit", evidence_bundle_id=None, prior_snapshot_id=None,
            falsifier=None, actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"c:{i}", requested_at=T))
        with OntologyUnitOfWork(engine) as uow:
            uow.finance.insert_outcome(OutcomeRow(
                outcome_id=f"mo-{i}", match_id=match, version=1, score_90="2-0", score_aet=None,
                penalties=None, status="final", source_artifact_retrieval_ids=[],
                recorded_at=T.isoformat(), supersedes_outcome_id=None))

    rows = compute_scorecard_rows(engine)
    by_card = {r["scorecard"]: r for r in rows}
    assert set(by_card) == {"forecast_truth", "market_information", "calibration"}
    truth = by_card["forecast_truth"]
    assert truth["n"] == 2 and truth["coverage"] == 1.0
    assert truth["brier_skill"] > 0                       # sharp belief beats the market prior
    calibration = json.loads(by_card["calibration"]["extra_json"])
    assert calibration["divergent"] == 2 and calibration["follow_market"] == 0
