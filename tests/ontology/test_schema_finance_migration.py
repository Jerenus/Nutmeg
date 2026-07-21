from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.schema import action_permissions


def test_finance_migration_creates_tables_and_seeds_permissions(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 8
    names = set(inspect(engine).get_table_names())
    assert {"budget_policies", "ticket_proposals", "tickets", "bet_legs", "cash_accounts",
            "cash_transactions", "match_outcomes", "bet_leg_settlements",
            "ticket_settlements"} <= names
    with engine.connect() as connection:
        pairs = {(r["action_type"], r["actor_role"])
                 for r in connection.execute(select(action_permissions)).mappings().all()}
    assert ("approve_ticket", "judge_operator") in pairs
    assert ("approve_ticket", "ai_analyst") not in pairs
    assert ("settle_ticket", "deterministic_system") in pairs
