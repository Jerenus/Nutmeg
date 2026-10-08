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

T = datetime(2026, 7, 19, 22, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _kernel_with_ticket(tmp_path: Path):
    settings = AppSettings(data_dir=tmp_path / "data")
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    seed_account(kernel.engine)
    service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    out = ForecastActions(service).commit_forecast(CommitForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id="sess-x",
        prior_distribution=PRIOR, belief_distribution=PRIOR, factors=[], commitment_tier="follow",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="c:1", requested_at=T))
    fr_id = out.result_refs[0].object_id
    ticket_id = seed_ticket(kernel.engine, [Leg("match-1", fr_id, stake=100.0, entry_odds=2.10)],
                            at=T.isoformat())
    return kernel, ticket_id


def test_reconcile_settles_match_tickets(tmp_path: Path) -> None:
    kernel, ticket_id = _kernel_with_ticket(tmp_path)
    result = kernel.reconcile.settle_match(ReconcileRequest(
        match_id="match-1", account_id="acct-jczq", score_90="2-1", status="final",
        source_artifact_retrieval_ids=[], actor_id="sys",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="rc:1", requested_at=T))
    assert result.outcome_id is not None
    assert result.settled_ticket_ids == (ticket_id,)
    assert kernel.status().settlement_count == 1
    assert ledger_balance(kernel.engine) == 110.0   # −100 stake + 100×2.10
