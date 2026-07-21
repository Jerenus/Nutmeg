from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.forecast_projection import compute_forecast_score_rows
from nutmeg.analytics.scoring import brier
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.market import SnapshotRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SHARP = {"home": 0.7, "draw": 0.2, "away": 0.1}


def _commit(svc, match, belief, key):
    return ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id=match, market_definition_id="md-had", decision_session_id=None,
        prior_distribution=PRIOR, belief_distribution=belief, factors=[], commitment_tier="commit",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key, requested_at=T))


def _outcome(uow, match, score, oid):
    uow.finance.insert_outcome(OutcomeRow(
        outcome_id=oid, match_id=match, version=1, score_90=score, score_aet=None, penalties=None,
        status="final", source_artifact_retrieval_ids=[], recorded_at=T.isoformat(),
        supersedes_outcome_id=None))


def _closing(uow, match, fair, sid):
    uow.market.insert_snapshot(SnapshotRow(
        market_snapshot_id=sid, match_id=match, market_definition_id="md-had",
        snapshot_kind="closing", as_of=T.isoformat(), fair_distribution=fair,
        devig_method="proportional", method_version="v1", source_coverage={}, freshness={},
        disagreement={}))


def test_forecast_scores_full_row(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    _commit(svc, "match-1", SHARP, "c:1")
    with OntologyUnitOfWork(engine) as uow:
        _outcome(uow, "match-1", "2-1", "mo-1")     # home win
        _closing(uow, "match-1", {"home": 0.72, "draw": 0.18, "away": 0.10}, "ms-1")
    rows = compute_forecast_score_rows(engine)
    assert len(rows) == 1
    row = rows[0]
    y = {"home": 1.0, "draw": 0.0, "away": 0.0}
    assert row["brier"] == brier(SHARP, y)
    assert row["prior_brier"] == brier(PRIOR, y)
    assert row["has_outcome"] is True and row["has_closing"] is True
    assert row["closing_skill_delta"] < 0        # sharp belief closer to closing than prior
    assert row["n_outcomes"] == 3


def test_forecast_scores_missing_inputs_are_flags_not_zero(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-2")
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    _commit(svc, "match-2", SHARP, "c:2")         # no outcome, no closing
    rows = compute_forecast_score_rows(engine)
    assert len(rows) == 1
    row = rows[0]
    assert row["has_outcome"] is False and row["brier"] is None       # not a fabricated 0
    assert row["has_closing"] is False and row["closing_skill_delta"] is None
