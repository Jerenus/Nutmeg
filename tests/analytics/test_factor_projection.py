from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.factor_projection import (
    compute_factor_contribution_rows,
    compute_factor_estimate_rows,
)
from nutmeg.ontology.actions.forecast_actions import (
    CommitForecastRequest,
    FactorInput,
    ForecastActions,
)
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _engine(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return engine


def _commit(svc, match, belief, factors, key):
    ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id=match, market_definition_id="md-had", decision_session_id=None,
        prior_distribution=PRIOR, belief_distribution=belief, factors=factors,
        commitment_tier="commit", evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None,
        actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key,
        requested_at=T))


def _outcome(uow, match, score, oid):
    uow.finance.insert_outcome(OutcomeRow(
        outcome_id=oid, match_id=match, version=1, score_90=score, score_aet=None, penalties=None,
        status="final", source_artifact_retrieval_ids=[], recorded_at=T.isoformat(),
        supersedes_outcome_id=None))


def test_contribution_and_confounded(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("m-ok")
        uow.identity.insert_match_minimal("m-conf")
    _commit(svc, "m-ok", {"home": 0.6, "draw": 0.25, "away": 0.15},
            [FactorInput("fd-rest", {"home": 0.1, "draw": -0.05, "away": -0.05}, [], [], None)],
            "c:ok")
    _commit(svc, "m-conf", dict(PRIOR), [
        FactorInput("fd-a", {"home": 0.6, "draw": -0.3, "away": -0.3}, [], [], None),
        FactorInput("fd-b", {"home": -0.6, "draw": 0.3, "away": 0.3}, [], [], None),
    ], "c:conf")
    with OntologyUnitOfWork(engine) as uow:
        _outcome(uow, "m-ok", "2-1", "mo-ok")
        _outcome(uow, "m-conf", "2-1", "mo-conf")

    rows = {(r["forecast_revision_id"], r["factor_definition_id"]): r
            for r in compute_factor_contribution_rows(engine)}
    ok = next(r for k, r in rows.items() if r["factor_definition_id"] == "fd-rest")
    assert ok["confounded"] is False and ok["brier_contribution"] is not None
    conf = [r for r in rows.values() if r["factor_definition_id"] in {"fd-a", "fd-b"}]
    assert len(conf) == 2 and all(r["confounded"] and r["brier_contribution"] is None
                                  for r in conf)


def test_small_sample_estimate_shrinks_toward_global(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    # fd-common in three home-win matches; fd-rare in one away-win match
    for i in range(3):
        match = f"m-c{i}"
        with OntologyUnitOfWork(engine) as uow:
            uow.identity.insert_match_minimal(match)
        common = FactorInput("fd-common", {"home": 0.15, "draw": -0.1, "away": -0.05}, [], [], None)
        _commit(svc, match, {"home": 0.65, "draw": 0.2, "away": 0.15}, [common], f"c:c{i}")
        with OntologyUnitOfWork(engine) as uow:
            _outcome(uow, match, "2-0", f"mo-c{i}")
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("m-rare")
    _commit(svc, "m-rare", {"home": 0.35, "draw": 0.25, "away": 0.40},
            [FactorInput("fd-rare", {"home": -0.15, "draw": -0.05, "away": 0.20}, [], [], None)],
            "c:rare")
    with OntologyUnitOfWork(engine) as uow:
        _outcome(uow, "m-rare", "0-2", "mo-rare")

    estimates = {r["factor_definition_id"]: r for r in compute_factor_estimate_rows(engine)}
    rare = estimates["fd-rare"]
    assert rare["n_eff"] == 1
    global_mean = (3 * estimates["fd-common"]["raw_mean"] + rare["raw_mean"]) / 4
    # shrunk estimate is pulled toward the global mean (closer than the raw mean is)
    assert abs(rare["shrunk_mean"] - global_mean) < abs(rare["raw_mean"] - global_mean)
