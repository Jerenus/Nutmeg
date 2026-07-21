from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.lifecycle import compute_lifecycle_proposal_rows
from nutmeg.ontology.actions.factor_actions import ApplyFactorStatusRequest, FactorActions
from nutmeg.ontology.actions.forecast_actions import (
    CommitForecastRequest,
    FactorInput,
    ForecastActions,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.decision import FactorDefinitionRow, FactorFamilyRow
from nutmeg.ontology.repository.finance import OutcomeRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _seed_probation_factor(engine) -> None:
    with OntologyUnitOfWork(engine) as uow:
        uow.decision.insert_factor_family(FactorFamilyRow("ff-rest", "rest", None))
        uow.decision.insert_factor_definition(FactorDefinitionRow(
            factor_definition_id="fd-good", factor_family_id="ff-rest", version=1, name="rest edge",
            definition=None, scope=None, status="probation", born_from_refs=[],
            valid_from=T.isoformat(), valid_to=None, policy_version="governance-v1"))


def _commit_win(svc, engine, match, key, oid):
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal(match)
    ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id=match, market_definition_id="md-had", decision_session_id=None,
        prior_distribution=PRIOR, belief_distribution={"home": 0.65, "draw": 0.2, "away": 0.15},
        factors=[FactorInput("fd-good", {"home": 0.15, "draw": -0.1, "away": -0.05}, [], [], None)],
        commitment_tier="commit", evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None,
        actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key,
        requested_at=T))
    with OntologyUnitOfWork(engine) as uow:
        uow.finance.insert_outcome(OutcomeRow(
            outcome_id=oid, match_id=match, version=1, score_90="2-0", score_aet=None,
            penalties=None, status="final", source_artifact_retrieval_ids=[],
            recorded_at=T.isoformat(), supersedes_outcome_id=None))


def test_lifecycle_proposes_but_action_applies(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    _seed_probation_factor(engine)
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    for i in range(3):
        _commit_win(svc, engine, f"m-{i}", f"c:{i}", f"mo-{i}")

    proposals = compute_lifecycle_proposal_rows(engine)
    promote = [p for p in proposals if p["factor_definition_id"] == "fd-good"]
    assert len(promote) == 1
    assert promote[0]["from_status"] == "probation" and promote[0]["to_status"] == "active"

    with OntologyUnitOfWork(engine) as uow:
        assert uow.decision.factor_status("fd-good") == "probation"   # projector changed nothing

    factor_actions = FactorActions(svc)
    denied = factor_actions.apply_factor_status(ApplyFactorStatusRequest(
        factor_definition_id="fd-good", target_status="active", actor_id="ai",
        actor_role=ActorRole.AI_ANALYST, idempotency_key="a:d", requested_at=T))
    assert denied.status is ActionStatus.REJECTED

    applied = factor_actions.apply_factor_status(ApplyFactorStatusRequest(
        factor_definition_id="fd-good", target_status="active", actor_id="op",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="a:1", requested_at=T))
    assert applied.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.decision.factor_status("fd-good") == "active"
