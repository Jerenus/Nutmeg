import json
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.regime import (
    compute_regime_postmatch_rows,
    compute_regime_vector_rows,
    market_shape,
)
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def test_market_shape_entropy() -> None:
    flat = market_shape({"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3})
    spiked = market_shape({"home": 0.9, "draw": 0.06, "away": 0.04})
    assert abs(flat["normalized_entropy"] - 1.0) < 1e-9
    assert spiked["normalized_entropy"] < 0.6
    assert spiked["favorite_concentration"] == 0.9


def _commit(svc, match, belief, key):
    ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id=match, market_definition_id="md-had", decision_session_id=None,
        prior_distribution=PRIOR, belief_distribution=belief, factors=[], commitment_tier="follow",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key, requested_at=T))


def test_regime_vectors_and_postmatch_separate(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    _commit(svc, "match-1", PRIOR, "c:1")

    vectors = compute_regime_vector_rows(engine)
    assert len(vectors) == 1
    axes = json.loads(vectors[0]["axes_json"])
    assert set(axes) == {"market_shape", "portfolio_risk", "information_weather",
                         "fixture_pressure", "data_health"}
    assert axes["information_weather"]["percentile"] == "percentile_unavailable"
    assert axes["market_shape"]["raw"]["favorite_concentration"] == 0.5

    # no outcome yet -> no post-match label (separate projection, no pre-match leakage)
    assert compute_regime_postmatch_rows(engine) == []
    with OntologyUnitOfWork(engine) as uow:
        uow.finance.insert_outcome(OutcomeRow(
            outcome_id="mo-1", match_id="match-1", version=1, score_90="0-2", score_aet=None,
            penalties=None, status="final", source_artifact_retrieval_ids=[],
            recorded_at=T.isoformat(), supersedes_outcome_id=None))
    post = compute_regime_postmatch_rows(engine)
    assert len(post) == 1
    assert json.loads(post[0]["labels_json"]) == ["upset"]   # home favorite lost 0-2
