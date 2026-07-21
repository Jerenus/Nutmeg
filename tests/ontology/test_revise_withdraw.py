from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.forecast_actions import (
    CommitForecastRequest,
    ForecastActions,
    WithdrawForecastRequest,
)
from nutmeg.ontology.actions.models import ActorRole
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


def _commit(key, belief) -> CommitForecastRequest:
    return CommitForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, belief_distribution=belief,
        factors=[], commitment_tier="follow", evidence_bundle_id=None, prior_snapshot_id=None,
        falsifier=None, actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key=key, requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC))


def _withdraw(key) -> WithdrawForecastRequest:
    return WithdrawForecastRequest(
        match_id="match-1", market_definition_id="md-had", actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 11, tzinfo=UTC))


def test_revise_then_withdraw(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    actions.commit_forecast(_commit("c:1", {"home": 0.5, "draw": 0.3, "away": 0.2}))
    actions.revise_forecast(_commit("r:1", {"home": 0.6, "draw": 0.25, "away": 0.15}))
    with OntologyUnitOfWork(engine) as uow:
        series = uow.decision.ensure_series("match-1", "md-had")
        assert uow.decision.count_committed_revisions() == 1
        current = uow.decision.current_committed_revision(series)
        assert abs(current.belief_distribution["home"] - 0.6) < 1e-9
        assert current.supersedes_revision_id is not None
    actions.withdraw_forecast(_withdraw("w:1"))
    with OntologyUnitOfWork(engine) as uow:
        series = uow.decision.ensure_series("match-1", "md-had")
        assert uow.decision.current_committed_revision(series) is None
        assert uow.decision.count_committed_revisions() == 0


def test_revise_without_current_is_rejected(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    with pytest.raises(ValueError, match="revise"):
        actions.revise_forecast(_commit("r:none", {"home": 0.5, "draw": 0.3, "away": 0.2}))
