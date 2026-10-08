from datetime import UTC, datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.finance.reconcile_flow import ReconcileRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from tests.ontology.ticket_seed import Leg, ledger_balance, seed_account, seed_ticket

T = datetime(2026, 7, 19, 20, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _commit(service: ActionService, match: str, key: str) -> str:
    out = ForecastActions(service).commit_forecast(CommitForecastRequest(
        match_id=match, market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution=PRIOR, belief_distribution=PRIOR, factors=[], commitment_tier="follow",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key=key, requested_at=T))
    return out.result_refs[0].object_id


def _book(kernel, match: str, fr_id: str) -> str:
    return seed_ticket(kernel.engine, [Leg(match, fr_id, stake=100.0, entry_odds=2.0)],
                       at=T.isoformat())


def test_package3b_ticket_to_settle_end_to_end(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-win")
        uow.identity.insert_match_minimal("match-open")   # will never get an outcome
    seed_account(kernel.engine)
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))

    # (1) commit a forecast, then book a had ticket on each match
    fr_win = _commit(service, "match-win", "c:win")
    fr_open = _commit(service, "match-open", "c:open")
    won = _book(kernel, "match-win", fr_win)
    _book(kernel, "match-open", fr_open)

    with OntologyUnitOfWork(kernel.engine) as uow:
        legs = uow.finance.bet_legs_for(won)
        assert len(legs) == 1
        assert legs[0].forecast_revision_id == fr_win   # BetLeg references committed forecast
    assert ledger_balance(kernel.engine) == -200.0   # two stakes

    # (2) reconcile match-win with a home win; match-open stays unreconciled
    result = kernel.reconcile.settle_match(ReconcileRequest(
        match_id="match-win", account_id="acct-jczq", score_90="2-0", status="final",
        source_artifact_retrieval_ids=[], actor_id="sys",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="rc:win", requested_at=T))
    assert result.settled_ticket_ids == (won,)

    with OntologyUnitOfWork(kernel.engine) as uow:
        # exactly one settlement — the open match created no pending settlement
        assert uow.finance.count_settlements() == 1
        assert uow.finance.current_outcome("match-open") is None
    # ledger reconciles: −200 stakes + 200 payout on the winning ticket = 0
    # (won ticket nets +100; the open ticket's −100 stake stays until it settles)
    assert ledger_balance(kernel.engine) == 0.0

    status = kernel.status()
    assert status.ticket_count == 2
    assert status.settlement_count == 1
