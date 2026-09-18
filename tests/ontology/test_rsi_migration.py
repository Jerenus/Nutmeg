from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations


def test_v29_creates_rsi_tables_and_seeds_constitutional_permissions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 29
    names = set(inspect(engine).get_table_names())
    for t in ("rsi_experiments", "rsi_duties", "rsi_duty_instances", "rsi_observations",
              "rsi_grades", "rsi_verdicts", "rsi_deployments", "rsi_amendments"):
        assert t in names, t
    with engine.connect() as c:
        rows = c.execute(select(schema.action_permissions.c.action_type,
                                schema.action_permissions.c.actor_role)
                         .where(schema.action_permissions.c.action_type.like("rsi_%"))).all()
    perms = {(a, r) for a, r in rows}
    # 宪法：人不能替 falsifier 说话；代码不能把东西推进票面
    assert ("rsi_record_verdict", "deterministic_system") in perms
    assert ("rsi_record_verdict", "judge_operator") not in perms
    assert ("rsi_approve_deployment", "judge_operator") in perms
    assert ("rsi_approve_deployment", "deterministic_system") not in perms
    assert ("rsi_register_experiment", "judge_operator") in perms
    assert ("rsi_register_experiment", "deterministic_system") not in perms
