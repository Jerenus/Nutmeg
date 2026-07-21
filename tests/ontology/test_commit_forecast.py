from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return ForecastActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _commit(key, belief, role=ActorRole.JUDGE_OPERATOR) -> CommitForecastRequest:
    return CommitForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, belief_distribution=belief,
        factors=[], commitment_tier="follow", evidence_bundle_id=None, prior_snapshot_id=None,
        falsifier=None, actor_id="op:owner", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC))


def test_commit_follow_market_belief_equals_prior(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.commit_forecast(_commit("c:1", {"home": 0.5, "draw": 0.3, "away": 0.2}))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        series = uow.decision.ensure_series("match-1", "md-had")
        current = uow.decision.current_committed_revision(series)
        assert current.status == "committed"
        assert current.commitment_tier == "follow"
        assert current.belief_distribution == current.prior_distribution


def test_second_commit_supersedes_and_keeps_single_current(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    actions.commit_forecast(_commit("c:1", {"home": 0.5, "draw": 0.3, "away": 0.2}))
    actions.commit_forecast(_commit("c:2", {"home": 0.55, "draw": 0.28, "away": 0.17}))
    with OntologyUnitOfWork(engine) as uow:
        series = uow.decision.ensure_series("match-1", "md-had")
        assert uow.decision.count_committed_revisions() == 1   # exactly one current committed
        current = uow.decision.current_committed_revision(series)
        assert abs(current.belief_distribution["home"] - 0.55) < 1e-9
        assert current.supersedes_revision_id is not None


def test_ai_analyst_cannot_commit(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.commit_forecast(_commit(
        "c:d", {"home": 0.5, "draw": 0.3, "away": 0.2}, ActorRole.AI_ANALYST))
    assert outcome.status is ActionStatus.REJECTED
