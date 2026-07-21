from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.forecast_actions import (
    DraftForecastRequest,
    FactorInput,
    ForecastActions,
)
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


def _req(key, belief, factors, role=ActorRole.AI_ANALYST) -> DraftForecastRequest:
    return DraftForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, belief_distribution=belief,
        factors=factors, commitment_tier="lean", evidence_bundle_id=None, prior_snapshot_id=None,
        falsifier="home xG < 1.0", actor_id="model:a", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 9, tzinfo=UTC))


def test_draft_with_conserving_deltas_commits(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.draft_forecast(_req(
        "d:1", {"home": 0.6, "draw": 0.25, "away": 0.15},
        [FactorInput(factor_definition_id="fd-x",
                     delta={"home": 0.1, "draw": -0.05, "away": -0.05},
                     scope_entity_ids=[], supporting_observation_ids=[], note="rest edge")]))
    assert outcome.status is ActionStatus.COMMITTED   # Action commits a row whose status is 'draft'
    with OntologyUnitOfWork(engine) as uow:
        series = uow.decision.ensure_series("match-1", "md-had")
        # the draft revision exists but is not a committed current
        assert uow.decision.current_committed_revision(series) is None
        assert uow.decision.max_revision_no(series) == 1


def test_draft_rejects_nonconserving_deltas(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    with pytest.raises(ValueError, match="delta"):
        actions.draft_forecast(_req(
            "d:2", {"home": 0.6, "draw": 0.25, "away": 0.15},
            [FactorInput(factor_definition_id="fd-x", delta={"home": 0.2, "draw": 0.0, "away": 0.0},
                         scope_entity_ids=[], supporting_observation_ids=[], note="wrong")]))


def test_connector_cannot_draft(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.draft_forecast(_req(
        "d:3", {"home": 0.5, "draw": 0.3, "away": 0.2}, [], ActorRole.CONNECTOR))
    assert outcome.status is ActionStatus.REJECTED
