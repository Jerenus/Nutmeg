from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.decision import (
    DecisionRepository,
    ForecastRevisionRow,
    SessionRow,
)
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _prepare(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return engine


def test_session_series_and_revision_persist(tmp_path: Path) -> None:
    engine = _prepare(tmp_path)
    now = datetime(2026, 7, 19, tzinfo=UTC).isoformat()
    with OntologyUnitOfWork(engine) as uow:
        repo: DecisionRepository = uow.decision
        repo.insert_session(SessionRow(
            decision_session_id="sess-1", opened_at=now, operator_id="op",
            cutoff_at=now, scope={"matches": ["match-1"]}, status="open", closed_at=None))
        series_id = repo.ensure_series("match-1", "md-had")
        again = repo.ensure_series("match-1", "md-had")
        assert series_id == again        # one series per (match, market)
        repo.insert_revision(ForecastRevisionRow(
            forecast_revision_id="fr-1", forecast_series_id=series_id, decision_session_id="sess-1",
            revision_no=1, status="committed", made_at=now, information_cutoff_at=now,
            prior_snapshot_id=None, prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
            belief_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, evidence_bundle_id=None,
            falsifier=None, actor_id="op", model_name=None, model_version=None,
            policy_version="governance-v1", commitment_tier="follow", evidence_coverage=None,
            evidence_quality=None, forecast_stability=None, supersedes_revision_id=None))
    with OntologyUnitOfWork(engine) as uow:
        current = uow.decision.current_committed_revision(series_id)
        assert current is not None
        assert current.forecast_revision_id == "fr-1"
        assert current.belief_distribution["home"] == 0.5
        assert uow.decision.count_committed_revisions() == 1
        assert uow.decision.max_revision_no(series_id) == 1
