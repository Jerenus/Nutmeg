"""Reads of append-only Zucai capital plans.

The commit Action was retired on 2026-10-08 (its CLI went in wave 2); `rsi` and the
product repository still read the plans already in production.
"""
import json

from sqlalchemy import insert

from nutmeg.ontology.repository import schema_capital as sc
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _plan(plan_id, issue="26130", *, supersedes=None, committed_at="2026-09-26T12:00:00+00:00",
          max_p_strict="0.03", gate_cost_pp="9.0"):
    return {
        "plan_id": plan_id, "issue": issue, "day": "2026-09-26", "supersedes": supersedes,
        "cap_source": "baseline", "adjudication_ref": None,
        "caps_json": json.dumps({"renjiu": 400, "shengfucai": 400, "total": 800}),
        "jczq_used_today": 0, "frontier_refs_json": json.dumps({"renjiu": "h" * 64}),
        "max_p_matrix": "0.12", "max_p_strict": max_p_strict, "chosen_p": "0.1",
        "gate_cost_pp": gate_cost_pp,
        "chosen_json": json.dumps([{"channel": "renjiu", "slip_id": None}]),
        "verdict_refs_json": "[]", "actor_id": "op:jun", "committed_at": committed_at,
    }


def _engine(tmp_path, *plans):
    engine = build_ontology_engine(tmp_path / "o.db")
    run_migrations(engine)
    with engine.begin() as connection:
        for plan in plans:
            connection.execute(insert(sc.zucai_capital_plans).values(**plan))
    return engine


def test_latest_plan_decodes_json_and_floats(tmp_path):
    engine = _engine(tmp_path, _plan("zcp-1"))
    with OntologyUnitOfWork(engine) as uow:
        plan = uow.capital.latest_plan("26130")
    assert plan.caps == {"renjiu": 400, "shengfucai": 400, "total": 800}
    assert abs(plan.gate_cost_pp - 9.0) < 1e-9
    assert plan.chosen[0]["slip_id"] is None


def test_supersession_picks_the_leaf_and_all_latest_spans_issues(tmp_path):
    engine = _engine(
        tmp_path,
        _plan("zcp-1"),
        _plan("zcp-2", supersedes="zcp-1", committed_at="2026-09-26T13:00:00+00:00",
              max_p_strict=None, gate_cost_pp=None),
        _plan("zcp-3", issue="26131"),
    )
    with OntologyUnitOfWork(engine) as uow:
        plan = uow.capital.latest_plan("26130")
        assert plan.plan_id == "zcp-2" and plan.gate_cost_pp is None
        assert len(uow.capital.plans("26130")) == 2
        assert uow.capital.latest_plan("26132") is None
        assert [p.plan_id for p in uow.capital.all_latest()] == ["zcp-2", "zcp-3"]
