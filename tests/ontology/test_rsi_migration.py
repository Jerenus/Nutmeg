from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import MIGRATIONS, migration_status, run_migrations
from nutmeg.ontology.repository.rsi import DutyInstanceRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


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


def test_pending_instrument_migration_keeps_fulfilled_and_removes_unfulfilled(tmp_path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine, MIGRATIONS[:35])
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO rsi_experiments "
            "(exp_id,claim,mechanism,tier,layer,population,min_tier,window_json,"
            "falsifier_json,stop_rule,quota_slot,buckets_json,rule_ids_json,source_doc,"
            "registered_at,frozen_hash,created_at) VALUES "
            "('F5','c','m','candidate','structural','both','price_only','{}','{}','s',"
            "0,'[]','[]','x','2026-09-18','h','2026-09-18')"
        )
        connection.exec_driver_sql(
            "INSERT INTO rsi_duties "
            "(duty_id,exp_id,recurrence,scope,deadline_rule,instrument_json,artifact_glob,"
            "description) VALUES "
            "('F5:price-band-observation','F5','per_day','match','match_kickoff',"
            "'[\"TODO\"]','x','x')"
        )
    with OntologyUnitOfWork(engine) as uow:
        for match_id, fulfilled_at in (("keep", "2026-09-19T01:00:00+08:00"), ("drop", None)):
            uow.rsi.insert_duty_instance(
                DutyInstanceRow(
                    duty_id="F5:price-band-observation",
                    day="2026-09-19",
                    match_id=match_id,
                    issue=None,
                    due_at="2026-09-19T00:30:00+08:00",
                    fulfilled_at=fulfilled_at,
                    artifact_path="x" if fulfilled_at else None,
                    artifact_hash="h" if fulfilled_at else None,
                )
            )

    run_migrations(engine)

    with OntologyUnitOfWork(engine) as uow:
        duty = uow.rsi.duties("F5")[0]
        assert duty.status == "pending_instrument"
        rows = uow.rsi.duty_instances_for_day(duty.duty_id, "2026-09-19")
        assert [(row.match_id, row.fulfilled_at is not None) for row in rows] == [
            ("keep", True)
        ]
