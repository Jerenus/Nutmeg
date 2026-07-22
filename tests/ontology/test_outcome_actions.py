from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.outcome_actions import (
    OutcomeActions,
    RecordOutcomeRequest,
    SettleTicketRequest,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.ticket_actions import (
    ApproveTicketRequest,
    LegInput,
    ProposeTicketRequest,
    TicketActions,
)
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T = datetime(2026, 7, 19, 22, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _setup(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        uow.finance.ensure_account(CashAccountRow(
            account_id="acct-jczq", channel_scope="jczq", currency="CNY", status="active"))
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    out = ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution=PRIOR, belief_distribution=PRIOR, factors=[], commitment_tier="follow",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="c:1", requested_at=T))
    return engine, svc, out.result_refs[0].object_id


def _record(key: str, score: str, role=ActorRole.DETERMINISTIC_SYSTEM) -> RecordOutcomeRequest:
    return RecordOutcomeRequest(
        match_id="match-1", score_90=score, status="final", source_artifact_retrieval_ids=[],
        actor_id="sys", actor_role=role, idempotency_key=key, requested_at=T)


def _approve_home_ticket(svc: ActionService, fr_id: str) -> str:
    tickets = TicketActions(svc)
    leg = LegInput(match_id="match-1", market_definition_id="md-had",
                   selection_id="sel-had-home", forecast_revision_id=fr_id,
                   bucket="main", stake=100.0, entry_odds=2.10)
    proposal = tickets.propose_ticket(ProposeTicketRequest(
        channel="jczq", decision_session_id="sess-x", legs=[leg], actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="pt:1", requested_at=T))
    approved = tickets.approve_ticket(ApproveTicketRequest(
        channel="jczq", account_id="acct-jczq", proposal_id=proposal.result_refs[0].object_id,
        legs=[leg], actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="at:1", requested_at=T))
    return next(r.object_id for r in approved.result_refs if r.object_type == "ticket")


def test_record_and_correct_outcome(tmp_path: Path) -> None:
    engine, svc, _fr = _setup(tmp_path)
    outcomes = OutcomeActions(svc)
    assert outcomes.record_outcome(_record("o:1", "2-1")).status is ActionStatus.COMMITTED
    outcomes.correct_outcome(_record("o:2", "1-1"))
    with OntologyUnitOfWork(engine) as uow:
        current = uow.finance.current_outcome("match-1")
        assert current.version == 2
        assert current.score_90 == "1-1"
        assert current.supersedes_outcome_id is not None
        assert uow.finance.max_outcome_version("match-1") == 2   # both versions kept


def test_connector_record_rejected(tmp_path: Path) -> None:
    _engine, svc, _fr = _setup(tmp_path)
    rejected = OutcomeActions(svc).record_outcome(_record("o:d", "0-0", ActorRole.CONNECTOR))
    assert rejected.status is ActionStatus.REJECTED


def test_settle_winning_ticket_pays_out(tmp_path: Path) -> None:
    engine, svc, fr_id = _setup(tmp_path)
    ticket_id = _approve_home_ticket(svc, fr_id)
    outcomes = OutcomeActions(svc)
    outcomes.record_outcome(_record("o:1", "2-1"))   # home win
    result = outcomes.settle_ticket(SettleTicketRequest(
        ticket_id=ticket_id, match_id="match-1", account_id="acct-jczq", actor_id="sys",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="st:1", requested_at=T))
    assert result.settled is True
    with OntologyUnitOfWork(engine) as uow:
        assert uow.finance.count_settlements() == 1
        # −100 stake + 100×2.10 odds-faithful payout = +110
        assert uow.finance.ledger_balance("acct-jczq") == 110.0


def test_settle_non_had_leg_grades_void(tmp_path: Path) -> None:
    engine, svc, _fr = _setup(tmp_path)
    out = ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id="match-1", market_definition_id="md-hhad", decision_session_id="sess-x",
        prior_distribution=PRIOR, belief_distribution=PRIOR, factors=[], commitment_tier="follow",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="c:hhad", requested_at=T))
    fr_hhad = out.result_refs[0].object_id
    tickets = TicketActions(svc)
    leg = LegInput(match_id="match-1", market_definition_id="md-hhad",
                   selection_id="sel-hhad-home", forecast_revision_id=fr_hhad,
                   bucket="hedge", stake=100.0, entry_odds=2.0, line="-1")
    proposal = tickets.propose_ticket(ProposeTicketRequest(
        channel="jczq", decision_session_id="sess-x", legs=[leg], actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="pt:h", requested_at=T))
    approved = tickets.approve_ticket(ApproveTicketRequest(
        channel="jczq", account_id="acct-jczq", proposal_id=proposal.result_refs[0].object_id,
        legs=[leg], actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="at:h", requested_at=T))
    ticket_id = next(r.object_id for r in approved.result_refs if r.object_type == "ticket")
    outcomes = OutcomeActions(svc)
    outcomes.record_outcome(_record("o:1", "2-1"))   # a home win at 90'
    outcomes.settle_ticket(SettleTicketRequest(
        ticket_id=ticket_id, match_id="match-1", account_id="acct-jczq", actor_id="sys",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="st:h", requested_at=T))
    with OntologyUnitOfWork(engine) as uow:
        grades = uow.connection.execute(select(sf.bet_leg_settlements.c.grade)).scalars().all()
        assert grades == ["void"]   # non-had market graded VOID, not mis-read as a loss
        # odds-faithful: a VOID leg is a push — the stake is refunded (×1.0), net 0
        assert uow.finance.ledger_balance("acct-jczq") == 0.0


def test_settle_missing_outcome_writes_no_pending(tmp_path: Path) -> None:
    engine, svc, fr_id = _setup(tmp_path)
    ticket_id = _approve_home_ticket(svc, fr_id)
    result = OutcomeActions(svc).settle_ticket(SettleTicketRequest(
        ticket_id=ticket_id, match_id="match-1", account_id="acct-jczq", actor_id="sys",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="st:x", requested_at=T))
    assert result.settled is False
    with OntologyUnitOfWork(engine) as uow:
        assert uow.finance.count_settlements() == 0   # never a pending loss
        assert uow.finance.ledger_balance("acct-jczq") == -100.0   # only the stake
