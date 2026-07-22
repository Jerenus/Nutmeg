from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.budget_actions import BudgetActions, ChangeBudgetPolicyRequest
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.ticket_actions import (
    ApproveTicketRequest,
    LegInput,
    ProposeTicketRequest,
    TicketActions,
)
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        uow.finance.ensure_account(CashAccountRow(
            account_id="acct-jczq", channel_scope="jczq", currency="CNY", status="active"))
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    forecast = ForecastActions(svc)
    out = forecast.commit_forecast(CommitForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution=PRIOR, belief_distribution=PRIOR, factors=[], commitment_tier="follow",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="c:1", requested_at=T))
    fr_id = out.result_refs[0].object_id
    return engine, TicketActions(svc), BudgetActions(svc), fr_id


def _leg(fr_id: str, stake: float = 100.0) -> LegInput:
    return LegInput(match_id="match-1", market_definition_id="md-had",
                    selection_id="sel-had-home", forecast_revision_id=fr_id,
                    bucket="main", stake=stake, entry_odds=2.10)


def _propose(tickets: TicketActions, legs, key="pt:1") -> str:
    out = tickets.propose_ticket(ProposeTicketRequest(
        channel="jczq", decision_session_id="sess-x", legs=legs, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key, requested_at=T))
    assert out.status is ActionStatus.COMMITTED
    return out.result_refs[0].object_id


def _approve(tickets: TicketActions, legs, proposal_id, key="at:1",
             role=ActorRole.JUDGE_OPERATOR):
    return tickets.approve_ticket(ApproveTicketRequest(
        channel="jczq", account_id="acct-jczq", proposal_id=proposal_id, legs=legs,
        actor_id="op:owner", actor_role=role, idempotency_key=key, requested_at=T))


def test_propose_then_approve_is_atomic(tmp_path: Path) -> None:
    engine, tickets, _budget, fr_id = _setup(tmp_path)
    legs = [_leg(fr_id)]
    proposal_id = _propose(tickets, legs)
    approved = _approve(tickets, legs, proposal_id)
    assert approved.status is ActionStatus.COMMITTED
    ticket_id = next(r.object_id for r in approved.result_refs if r.object_type == "ticket")
    with OntologyUnitOfWork(engine) as uow:
        assert uow.finance.count_tickets() == 1
        assert len(uow.finance.bet_leg_ids(ticket_id)) == 1
        assert uow.finance.ledger_balance("acct-jczq") == -100.0


def test_leg_without_committed_forecast_rejected(tmp_path: Path) -> None:
    _engine, tickets, _budget, _fr_id = _setup(tmp_path)
    bogus = [_leg("fr-does-not-exist")]
    with pytest.raises(ValueError, match="committed"):
        _propose(tickets, bogus, key="pt:bogus")


def test_ai_analyst_approve_rejected(tmp_path: Path) -> None:
    _engine, tickets, _budget, fr_id = _setup(tmp_path)
    legs = [_leg(fr_id)]
    proposal_id = _propose(tickets, legs)
    approved = _approve(tickets, legs, proposal_id, key="at:d", role=ActorRole.AI_ANALYST)
    assert approved.status is ActionStatus.REJECTED


def test_over_budget_approve_raises(tmp_path: Path) -> None:
    _engine, tickets, budget, fr_id = _setup(tmp_path)
    budget.change_budget_policy(ChangeBudgetPolicyRequest(
        channel="jczq", total_cap=50.0, bucket_caps={"main": 50.0}, policy_version="budget-v1",
        actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="bp:1",
        requested_at=T))
    legs = [_leg(fr_id, stake=100.0)]
    proposal_id = _propose(tickets, legs)
    with pytest.raises(ValueError, match="cap"):
        _approve(tickets, legs, proposal_id, key="at:over")
