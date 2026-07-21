from pathlib import Path

from sqlalchemy import inspect

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations


def test_context_migration_creates_tables(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 5
    names = set(inspect(engine).get_table_names())
    assert {"persons", "role_assignments", "person_match_statuses", "lineup_entries"} <= names


def test_context_migration_is_idempotent(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert run_migrations(engine).applied_versions == ()
