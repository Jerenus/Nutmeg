from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations


def test_migration_10_adds_workflow_outbox_and_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")

    report = run_migrations(engine)

    assert report.applied_versions[-1] == 10
    assert {
        "adjudications",
        "flag_instances",
        "predictions",
        "precedent_links",
        "agent_proposals",
        "outbox_events",
    } <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        permissions = {
            (row.action_type, row.actor_role)
            for row in connection.execute(select(schema.action_permissions))
        }
    assert ("record_adjudication", "judge_operator") in permissions
    assert ("create_agent_proposal", "ai_analyst") in permissions
    assert ("resolve_agent_proposal", "judge_operator") in permissions
