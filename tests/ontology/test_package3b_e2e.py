from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.ticket_actions import LegInput
from nutmeg.ontology.finance.express_flow import ExpressRequest
from nutmeg.ontology.finance.reconcile_flow import ReconcileRequest
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

T = datetime(2026, 7, 19, 20, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _commit(service: ActionService, match: str, key: str) -> str:
    out = ForecastActions(service).commit_forecast(CommitForecastRequest(
        match_id=match, market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution=PRIOR, belief_distribution=PRIOR, factors=[], commitment_tier="follow",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key, requested_at=T))
    return out.result_refs[0].object_id


def _express(kernel, account: str, match: str, fr_id: str, key: str):
    leg = LegInput(match_id=match, market_definition_id="md-had", selection_id="sel-had-home",
                   forecast_revision_id=fr_id, bucket="main", stake=100.0, entry_odds=2.0)
    return kernel.express.approve_for_match(ExpressRequest(
        channel="jczq", account_id=account, decision_session_id="sess-x", legs=[leg],
        actor_id="op:owner", actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key,
        requested_at=T))


def test_package3b_express_to_settle_end_to_end(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-win")
        uow.identity.insert_match_minimal("match-open")   # will never get an outcome
        uow.finance.ensure_account(CashAccountRow(
            account_id="acct-jczq", channel_scope="jczq", currency="CNY", status="active"))
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))

    # (1) commit a forecast, then express-approve a had leg for each match
    fr_win = _commit(service, "match-win", "c:win")
    fr_open = _commit(service, "match-open", "c:open")
    won = _express(kernel, "acct-jczq", "match-win", fr_win, "ex:win")
    _express(kernel, "acct-jczq", "match-open", fr_open, "ex:open")

    # atomic approve wrote Ticket + BetLeg (referencing the committed forecast) + stake
    with OntologyUnitOfWork(kernel.engine) as uow:
        legs = uow.finance.bet_legs_for(won.ticket_id)
        assert len(legs) == 1
        assert legs[0].forecast_revision_id == fr_win   # BetLeg references committed forecast
        assert uow.finance.ledger_balance("acct-jczq") == -200.0   # two stakes

    # (2) reconcile match-win with a home win; match-open stays unreconciled
    result = kernel.reconcile.settle_match(ReconcileRequest(
        match_id="match-win", account_id="acct-jczq", score_90="2-0", status="final",
        source_artifact_retrieval_ids=[], actor_id="sys",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="rc:win", requested_at=T))
    assert result.settled_ticket_ids == (won.ticket_id,)

    with OntologyUnitOfWork(kernel.engine) as uow:
        # exactly one settlement — the open match created no pending settlement
        assert uow.finance.count_settlements() == 1
        assert uow.finance.current_outcome("match-open") is None
        # ledger reconciles: −200 stakes + 200 payout on the winning ticket = 0
        # (won ticket nets +100; the open ticket's −100 stake stays until it settles)
        assert uow.finance.ledger_balance("acct-jczq") == 0.0

    status = kernel.status()
    assert status.ticket_count == 2
    assert status.settlement_count == 1
