import json
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.analytics.integrity_action import compute_integrity_action_rows
from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.finance.reconcile_flow import ReconcileRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from tests.ontology.ticket_seed import Leg, seed_account, seed_ticket

T = datetime(2026, 7, 19, 10, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def test_action_and_integrity_cards(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    seed_account(kernel.engine)
    svc = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    out = ForecastActions(svc).commit_forecast(CommitForecastRequest(
        match_id="match-1", market_definition_id="md-had", decision_session_id=None,
        prior_distribution=PRIOR, belief_distribution=PRIOR, factors=[], commitment_tier="follow",
        evidence_bundle_id=None, prior_snapshot_id=None, falsifier=None, actor_id="op:owner",
        actor_role=ActorRole.JUDGE_OPERATOR, idempotency_key="c:1", requested_at=T))
    fr = out.result_refs[0].object_id
    seed_ticket(kernel.engine, [Leg("match-1", fr, stake=100.0, entry_odds=2.10)],
                at=T.isoformat())
    kernel.reconcile.settle_match(ReconcileRequest(
        match_id="match-1", account_id="acct-jczq", score_90="2-0", status="final",
        source_artifact_retrieval_ids=[], actor_id="sys",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key="rc:1", requested_at=T))

    cards = {r["scorecard"]: json.loads(r["metrics_json"])
             for r in compute_integrity_action_rows(kernel.engine)}
    action = cards["action_finance"]
    assert action["stake_total"] == 100.0 and action["payout_total"] == 210.0
    assert action["ledger_balance"] == 110.0        # odds-faithful: 100×2.10 payout
    assert action["ticket_count"] == 1 and action["settlement_count"] == 1
    integrity = cards["evidence_integrity"]
    assert integrity["outcome_completeness"] == 1.0    # the one revision's match has an outcome
    assert integrity["closing_coverage"] == 0.0
