from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema import action_permissions


def test_evidence_migration_creates_tables_and_seeds_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 6
    names = set(inspect(engine).get_table_names())
    assert {"claims", "claim_status_events", "claim_evidence_spans", "observations",
            "observation_sources", "observation_claims"} <= names
    with engine.connect() as connection:
        rows = connection.execute(select(action_permissions)).mappings().all()
        pairs = {(row["action_type"], row["actor_role"]) for row in rows}
    assert ("extract_claim", "ai_extractor") in pairs
    assert ("record_observation", "connector") in pairs
    assert ("verify_claim", "judge_operator") in pairs
    assert ("extract_claim", "connector") not in pairs   # AI-only path stays AI-only
    assert ("record_observation", "ai_extractor") not in pairs   # AI never writes verified facts
