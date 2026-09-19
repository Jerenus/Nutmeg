from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.capital_actions import CapitalActions, CommitCapitalPlanRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T0 = datetime(2026, 9, 19, 12, tzinfo=UTC)
HUMAN = {"actor_id": "op:jun", "actor_role": ActorRole.JUDGE_OPERATOR}
SYSTEM = {"actor_id": "sys:plan", "actor_role": ActorRole.DETERMINISTIC_SYSTEM}


def _rig(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 30
    return CapitalActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(
    key,
    *,
    cap_source="baseline",
    adjudication_ref=None,
    caps=None,
    role=HUMAN,
    supersedes=None,
):
    return CommitCapitalPlanRequest(
        issue="26130",
        day="2026-09-26",
        cap_source=cap_source,
        adjudication_ref=adjudication_ref,
        caps=caps or {"renjiu": 400, "shengfucai": 400, "total": 800},
        jczq_used_today=0,
        frontier_refs={"renjiu": "h" * 64},
        max_p_matrix=0.12,
        max_p_strict=0.03,
        chosen_p=0.10,
        chosen=[
            {
                "channel": "renjiu",
                "candidate_node": "chosen#0@renjiu",
                "legs_file_hash": "l" * 64,
                "notes": 200,
                "stake_yuan": 400,
                "p_all": 0.10,
            }
        ],
        verdict_refs=[],
        supersedes=supersedes,
        idempotency_key=key,
        requested_at=T0,
        **role,
    )


def test_commit_is_human_only_and_records_gate_cost(tmp_path):
    actions, engine = _rig(tmp_path)
    assert actions.commit_capital_plan(_req("c:sys", role=SYSTEM)).status is ActionStatus.REJECTED
    outcome = actions.commit_capital_plan(_req("c:h"))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        plan = uow.capital.latest_plan("26130")
        assert plan.cap_source == "baseline" and abs(plan.gate_cost_pp - 9.0) < 1e-9
        assert plan.chosen[0]["slip_id"] is None


def test_override_requires_an_adjudication_and_caps_are_enforced(tmp_path):
    actions, _ = _rig(tmp_path)
    with pytest.raises(ValueError, match="adjudication"):
        actions.commit_capital_plan(_req("c:o", cap_source="override"))
    with pytest.raises(ValueError, match="renjiu"):
        actions.commit_capital_plan(
            _req(
                "c:cap",
                cap_source="override",
                adjudication_ref="ADJ-1",
                caps={"renjiu": 1300, "shengfucai": 0, "total": 1300},
            )
        )


def test_recommit_supersedes_and_strict_empty_gives_none_gate_cost(tmp_path):
    actions, engine = _rig(tmp_path)
    first = actions.commit_capital_plan(_req("c:1"))
    plan_id = first.result_refs[0].object_id
    actions.commit_capital_plan(replace(_req("c:2", supersedes=plan_id), max_p_strict=None))
    with OntologyUnitOfWork(engine) as uow:
        plan = uow.capital.latest_plan("26130")
        assert plan.supersedes == plan_id and plan.gate_cost_pp is None
        assert len(uow.capital.plans("26130")) == 2
