from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.factor_actions import (
    ApplyFactorStatusRequest,
    FactorActions,
    ProposeFactorStatusRequest,
)
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.decision import FactorDefinitionRow, FactorFamilyRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.decision.insert_factor_family(FactorFamilyRow(
            factor_family_id="ff-1", name="rest", definition=None))
        uow.decision.insert_factor_definition(FactorDefinitionRow(
            factor_definition_id="fd-1", factor_family_id="ff-1", version=1, name="rest_edge",
            definition=None, scope=None, status="probation", born_from_refs=[],
            valid_from="2026-07-19T00:00:00+08:00", valid_to=None, policy_version="governance-v1"))
    return FactorActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _apply(key, target, role=ActorRole.JUDGE_OPERATOR) -> ApplyFactorStatusRequest:
    return ApplyFactorStatusRequest(
        factor_definition_id="fd-1", target_status=target, actor_id="op:owner", actor_role=role,
        idempotency_key=key, requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC))


def test_factor_lifecycle_probation_to_active(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    outcome = actions.apply_factor_status(_apply("af:1", "active"))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        assert uow.decision.factor_status("fd-1") == "active"


def test_ai_analyst_can_propose_but_not_apply(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    proposed = actions.propose_factor_status(ProposeFactorStatusRequest(
        factor_definition_id="fd-1", target_status="active", rationale="n=32 skill>0",
        actor_id="model:a", actor_role=ActorRole.AI_ANALYST, idempotency_key="pf:1",
        requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC)))
    assert proposed.status is ActionStatus.COMMITTED
    denied = actions.apply_factor_status(_apply("af:d", "active", ActorRole.AI_ANALYST))
    assert denied.status is ActionStatus.REJECTED
