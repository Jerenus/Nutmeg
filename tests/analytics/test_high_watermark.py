from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.high_watermark import high_watermark
from nutmeg.ontology.actions.budget_actions import BudgetActions, ChangeBudgetPolicyRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.paths import OntologyPaths
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def test_watermark_monotonic(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    before = high_watermark(engine)
    BudgetActions(ActionService(lambda: OntologyUnitOfWork(engine))).change_budget_policy(
        ChangeBudgetPolicyRequest(
            channel="jczq", total_cap=400.0, bucket_caps={}, policy_version="budget-v1",
            actor_id="op", actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="bp:1",
            requested_at=datetime(2026, 7, 19, tzinfo=UTC)))
    assert high_watermark(engine) > before


def test_analytics_path(tmp_path: Path) -> None:
    paths = OntologyPaths.from_data_dir(tmp_path)
    assert paths.analytics == tmp_path / "ontology" / "analytics.duckdb"
