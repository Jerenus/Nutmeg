from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.decision import ForecastRevisionRow
from nutmeg.ontology.repository.finance import (
    BetLegRow,
    CashAccountRow,
    CashTransactionRow,
    FinanceRepository,
    TicketRow,
)
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _prepare(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    now = datetime(2026, 7, 19, tzinfo=UTC).isoformat()
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
        series = uow.decision.ensure_series("match-1", "md-had")
        uow.decision.insert_revision(ForecastRevisionRow(
            forecast_revision_id="fr-1", forecast_series_id=series, decision_session_id=None,
            revision_no=1, status="committed", made_at=now, information_cutoff_at=None,
            prior_snapshot_id=None, prior_distribution={"home": 0.5, "draw": 0.3, "away": 0.2},
            belief_distribution={"home": 0.5, "draw": 0.3, "away": 0.2}, evidence_bundle_id=None,
            falsifier=None, actor_id="op", model_name=None, model_version=None,
            policy_version="governance-v1", commitment_tier="follow", evidence_coverage=None,
            evidence_quality=None, forecast_stability=None, supersedes_revision_id=None))
    return engine, now


def test_ledger_and_legs(tmp_path: Path) -> None:
    engine, now = _prepare(tmp_path)
    with OntologyUnitOfWork(engine) as uow:
        repo: FinanceRepository = uow.finance
        repo.ensure_account(CashAccountRow(
            account_id="acct-jczq", channel_scope="jczq", currency="CNY", status="active"))
        repo.insert_ticket(TicketRow(
            ticket_id="tk-1", channel="jczq", proposal_id=None, approved_at=now, status="approved",
            structure="single", total_stake=100.0, currency="CNY", account_id="acct-jczq"))
        repo.insert_bet_leg(BetLegRow(
            bet_leg_id="bl-1", ticket_id="tk-1", forecast_revision_id="fr-1", match_id="match-1",
            market_definition_id="md-had", selection_id="sel-had-home", entry_quote_id=None,
            line=None, stake_share=100.0))
        repo.insert_cash_transaction(CashTransactionRow(
            transaction_id="cx-1", account_id="acct-jczq", ticket_id="tk-1",
            ticket_settlement_id=None, kind="stake", amount=-100.0, occurred_at=now,
            idempotency_key="stake:tk-1"))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.finance.count_tickets() == 1
        assert uow.finance.bet_leg_ids("tk-1") == ("bl-1",)
        assert uow.finance.ledger_balance("acct-jczq") == -100.0
