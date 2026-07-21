from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema_market import market_definitions


def test_market_migration_creates_tables_and_seeds_definitions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 4
    names = set(inspect(engine).get_table_names())
    assert {"market_definitions", "selection_definitions", "market_quotes", "market_snapshots",
            "market_snapshot_quotes"} <= names
    with engine.connect() as connection:
        kinds = set(
            connection.execute(select(market_definitions.c.market_kind)).scalars().all()
        )
    assert {"had", "hhad", "ttg", "crs"} <= kinds
