from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations


def test_migration_18_applies_fresh_and_from_v17(tmp_path: Path) -> None:
    expected_tables = {
        "operator_evidence_intake_receipts",
        "operator_evidence_coverage_receipts",
        "operator_evidence_intake_objects",
    }

    for name, initial in (
        ("fresh", MIGRATIONS[:18]),
        ("upgrade", MIGRATIONS[:17]),
    ):
        engine = build_ontology_engine(tmp_path / f"{name}.db")
        run_migrations(engine, initial)
        run_migrations(engine, MIGRATIONS[:18])

        assert migration_status(engine).current_version == 18
        assert expected_tables <= set(inspect(engine).get_table_names())
        object_columns = {
            column["name"]
            for column in inspect(engine).get_columns("operator_evidence_intake_objects")
        }
        assert {
            "observed_at",
            "source_kinds_json",
            "source_retrieval_ids_json",
        } <= object_columns

        with engine.connect() as connection:
            permissions = {
                (row.action_type, row.actor_role)
                for row in connection.execute(
                    select(
                        schema.action_permissions.c.action_type,
                        schema.action_permissions.c.actor_role,
                    ).where(
                        schema.action_permissions.c.action_type
                        == "ingest_operator_evidence_manifest"
                    )
                )
            }

        assert permissions == {
            ("ingest_operator_evidence_manifest", "deterministic_system")
        }
