from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.budget_actions import BudgetActions, ChangeBudgetPolicyRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    return BudgetActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key: str, role: ActorRole = ActorRole.JUDGE_OPERATOR) -> ChangeBudgetPolicyRequest:
    return ChangeBudgetPolicyRequest(
        channel="jczq", total_cap=400.0,
        bucket_caps={"main": 100.0, "hedge": 100.0, "draw": 40.0, "parlay": 60.0},
        policy_version="budget-v1", actor_id="op:owner", actor_role=role, idempotency_key=key,
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC))


def test_change_budget_policy_commits(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    assert actions.change_budget_policy(_req("bp:1")).status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        policy = uow.finance.active_budget_policy("jczq")
        assert policy.total_cap == 400.0
        assert policy.bucket_caps["main"] == 100.0


def test_ai_analyst_cannot_change_budget(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    assert actions.change_budget_policy(
        _req("bp:d", ActorRole.AI_ANALYST)).status is ActionStatus.REJECTED
