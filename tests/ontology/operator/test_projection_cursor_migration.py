from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations


def test_migration_27_adds_independent_projection_cursors_fresh_and_from_v26(
    tmp_path: Path,
) -> None:
    for name, migrations in (
        ("fresh", MIGRATIONS),
        ("upgrade", MIGRATIONS[:26]),
    ):
        engine = build_ontology_engine(tmp_path / name / "ontology.db")
        run_migrations(engine, migrations)
        if name == "upgrade":
            assert migration_status(engine).current_version == 26
            run_migrations(engine)

        assert 27 in migration_status(engine).applied_versions
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("operator_projection_cursors")
        }
        assert columns == {"consumer_name", "last_sequence", "updated_at"}
