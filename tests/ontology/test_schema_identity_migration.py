from pathlib import Path

from sqlalchemy import func, inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema_identity import entity_aliases, teams


def test_identity_migration_creates_tables_and_seeds_aliases(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 3
    names = set(inspect(engine).get_table_names())
    assert {"competitions", "competition_editions", "teams", "venues", "matches",
            "match_revisions", "team_appearances", "external_identifiers", "entity_aliases",
            "entity_merges"} <= names
    with engine.connect() as connection:
        alias_count = connection.execute(
            select(func.count()).select_from(entity_aliases)
        ).scalar_one()
        assert alias_count > 0
        assert connection.execute(
            select(func.count()).select_from(entity_aliases).where(
                entity_aliases.c.entity_type == "team"
            )
        ).scalar_one() > 0
    assert teams.c.resolution_status is not None


def test_identity_migration_is_idempotent(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    second = run_migrations(engine)
    assert second.applied_versions == ()
