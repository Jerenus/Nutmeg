from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.decision import ForecastRevisionRow
from nutmeg.ontology.repository.finance import CashTransactionRow, FinanceRepository
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.ticket_seed import Leg, ledger_balance, seed_account, seed_ticket


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


def test_ticket_reads_and_cash_ledger(tmp_path: Path) -> None:
    engine, now = _prepare(tmp_path)
    seed_account(engine)
    ticket_id = seed_ticket(engine, [Leg("match-1", "fr-1", stake=100.0, entry_odds=None)],
                            at=now)
    with OntologyUnitOfWork(engine) as uow:
        repo: FinanceRepository = uow.finance
        repo.insert_cash_transaction(CashTransactionRow(
            transaction_id="cx-adj", account_id="acct-jczq", ticket_id=None,
            ticket_settlement_id=None, kind="adjustment", amount=5.0, occurred_at=now,
            idempotency_key="adj:1"))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.finance.count_tickets() == 1
        assert uow.finance.tickets_for_match("match-1") == (ticket_id,)
        [leg] = uow.finance.bet_legs_for(ticket_id)
        assert leg.forecast_revision_id == "fr-1" and leg.stake_share == 100.0
    assert ledger_balance(engine) == -95.0
