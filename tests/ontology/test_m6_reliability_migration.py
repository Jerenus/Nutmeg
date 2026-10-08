from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.repository import schema, schema_reliability
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, run_migrations
from nutmeg.ontology.wiring import build_ontology_kernel

RELIABILITY_PERMISSIONS = {
    ("record_reliability_evidence", "deterministic_system"),
    ("record_reliability_evidence", "judge_operator"),
    ("approve_release", "judge_operator"),
}
SCOREBOARD_PERMISSIONS = {
    ("record_scoreboard_observation", "judge_operator"),
    ("approve_scoreboard_cutover", "judge_operator"),
    ("record_scoreboard_shadow_review", "deterministic_system"),
    ("record_scoreboard_export", "deterministic_system"),
}


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    report = kernel.initialize()
    return kernel, report


def test_migration_14_creates_tables_and_exact_permissions(tmp_path: Path) -> None:
    kernel, report = _kernel(tmp_path)

    assert 14 in report.applied_versions
    assert {"reliability_evidence", "release_approvals"} <= set(
        inspect(kernel.engine).get_table_names()
    )
    with kernel.engine.connect() as connection:
        rows = connection.execute(select(schema.action_permissions)).mappings().all()
    seeded = {
        (row["action_type"], row["actor_role"])
        for row in rows
        if row["action_type"]
        in {"record_reliability_evidence", "approve_release"}
    }
    assert seeded == RELIABILITY_PERMISSIONS
    assert schema_reliability.reliability_evidence.c.action_id.unique is True
    assert schema_reliability.release_approvals.c.release_version.unique is True


def test_migration_14_upgrades_an_existing_schema_13_store(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.sqlite3")
    assert run_migrations(engine, migrations=MIGRATIONS[:13]).applied_versions[-1] == 13
    with engine.connect() as connection:
        before = connection.execute(select(schema.action_permissions)).mappings().all()
    assert SCOREBOARD_PERMISSIONS <= {
        (row["action_type"], row["actor_role"]) for row in before
    }

    report = run_migrations(engine, migrations=MIGRATIONS[:14])

    assert report.applied_versions == (14,)
    with engine.connect() as connection:
        rows = connection.execute(select(schema.action_permissions)).mappings().all()
    seeded = {
        (row["action_type"], row["actor_role"])
        for row in rows
        if row["action_type"]
        in {"record_reliability_evidence", "approve_release"}
    }
    assert seeded == RELIABILITY_PERMISSIONS
