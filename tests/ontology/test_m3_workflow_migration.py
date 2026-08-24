from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, run_migrations


def test_migration_11_adds_proposal_cutoff_prompt_and_tightens_permission(
    tmp_path: Path,
) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine, migrations=MIGRATIONS[:10])
    with engine.begin() as connection:
        columns = {
            item["name"] for item in inspect(engine).get_columns("agent_proposals")
        }
        for column in ("information_cutoff_at", "operator_prompt"):
            if column in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE agent_proposals DROP COLUMN {column}"
                )
    before = {
        item["name"] for item in inspect(engine).get_columns("agent_proposals")
    }
    assert "information_cutoff_at" not in before
    assert "operator_prompt" not in before

    report = run_migrations(engine, migrations=MIGRATIONS[:11])

    assert report.applied_versions == (11,)
    columns = {
        item["name"] for item in inspect(engine).get_columns("agent_proposals")
    }
    assert {"information_cutoff_at", "operator_prompt"} <= columns
    with engine.connect() as connection:
        roles = connection.execute(
            select(schema.action_permissions.c.actor_role).where(
                schema.action_permissions.c.policy_version_id == "governance-v1",
                schema.action_permissions.c.action_type == "create_agent_proposal",
            )
        ).scalars().all()
    assert roles == ["ai_analyst"]


def test_migration_11_reopens_without_reapplying(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")

    assert run_migrations(engine, migrations=MIGRATIONS[:11]).applied_versions[-1] == 11
    assert run_migrations(engine, migrations=MIGRATIONS[:11]).applied_versions == ()
