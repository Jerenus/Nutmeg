from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.decision.read_flow import ReadMatchRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel


def test_read_flow_commits_a_forecast(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    result = kernel.decision_read.read_match(ReadMatchRequest(
        match_id="match-1", market_definition_id="md-had", operator_id="op:owner",
        cutoff_at="2026-07-19T15:00:00+08:00",
        prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
        belief_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, factors=[],
        actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        requested_at=datetime(2026, 7, 19, 10, tzinfo=UTC)))
    assert result.committed is True
    status = kernel.status()
    assert status.forecast_count == 1
    assert status.bundle_count == 1
