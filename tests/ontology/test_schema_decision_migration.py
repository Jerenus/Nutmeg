from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema import action_permissions


def test_decision_migration_creates_tables_and_seeds_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 7
    names = set(inspect(engine).get_table_names())
    assert {"decision_sessions", "evidence_bundles", "evidence_bundle_items", "forecast_series",
            "forecast_revisions", "factor_families", "factor_definitions", "factor_applications",
            "scenarios"} <= names
    with engine.connect() as connection:
        pairs = {(r["action_type"], r["actor_role"])
                 for r in connection.execute(select(action_permissions)).mappings().all()}
    assert ("draft_forecast", "ai_analyst") in pairs
    assert ("commit_forecast", "judge_operator") in pairs
    assert ("commit_forecast", "ai_analyst") not in pairs   # AI cannot commit
    assert ("freeze_evidence_bundle", "deterministic_system") in pairs
