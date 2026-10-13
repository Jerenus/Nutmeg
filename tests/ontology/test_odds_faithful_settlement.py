from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text

from nutmeg.ontology.actions.forecast_actions import CommitForecastRequest, ForecastActions
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.outcome_actions import (
    OutcomeActions,
    RecordOutcomeRequest,
    SettleTicketRequest,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.ticket_seed import Leg, ledger_balance, seed_account, seed_ticket

T = datetime(2026, 7, 22, 12, tzinfo=UTC)
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}


def _setup(tmp_path: Path, matches: tuple[str, ...] = ("m-1",)):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        for match in matches:
            uow.identity.insert_match_minimal(match)
    seed_account(engine)
    svc = ActionService(lambda: OntologyUnitOfWork(engine))
    revisions = {}
    for i, match in enumerate(matches):
        out = ForecastActions(svc).commit_forecast(CommitForecastRequest(
            match_id=match, market_definition_id="md-had", decision_session_id=None,
            prior_distribution=PRIOR, belief_distribution=PRIOR, factors=[],
            commitment_tier="follow", evidence_bundle_id=None, prior_snapshot_id=None,
            falsifier=None, actor_id="op", actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"c:{i}", requested_at=T))
        revisions[match] = out.result_refs[0].object_id
    return engine, svc, revisions


def _approve(engine, legs):
    return seed_ticket(engine, legs, at=T.isoformat())


def _record(svc, match, score, key):
    OutcomeActions(svc).record_outcome(RecordOutcomeRequest(
        match_id=match, score_90=score, status="final", source_artifact_retrieval_ids=[],
        actor_id="sys", actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key=key,
        requested_at=T))


def _settle(svc, ticket_id, match, key):
    return OutcomeActions(svc).settle_ticket(SettleTicketRequest(
        ticket_id=ticket_id, match_id=match, account_id="acct-jczq", actor_id="sys",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM, idempotency_key=key, requested_at=T))


def _leg(match, fr, odds, stake=100.0, selection="sel-had-home"):
    return Leg(match, fr, stake=stake, entry_odds=odds, selection_id=selection)


def test_single_win_pays_stake_times_odds(tmp_path: Path) -> None:
    engine, svc, fr = _setup(tmp_path)
    ticket = _approve(engine, [_leg("m-1", fr["m-1"], 1.65)])
    _record(svc, "m-1", "2-0", "o:1")
    _settle(svc, ticket, "m-1", "s:1")
    with OntologyUnitOfWork(engine) as uow:
        assert ledger_balance(engine) == pytest.approx(65.0)   # -100 + 165
        method = uow.connection.execute(
            select(sf.ticket_settlements.c.settlement_method_version)).scalar_one()
        assert method == "odds-faithful-v1"


def test_single_loss_pays_zero(tmp_path: Path) -> None:
    engine, svc, fr = _setup(tmp_path)
    ticket = _approve(engine, [_leg("m-1", fr["m-1"], 1.65)])
    _record(svc, "m-1", "0-2", "o:1")   # away wins, home leg loses
    _settle(svc, ticket, "m-1", "s:1")
    assert ledger_balance(engine) == -100.0


def test_parlay_multiplies_leg_odds(tmp_path: Path) -> None:
    engine, svc, fr = _setup(tmp_path, ("m-1", "m-2"))
    legs = [_leg("m-1", fr["m-1"], 2.0, stake=30.0),
            _leg("m-2", fr["m-2"], 1.5, stake=30.0)]
    ticket = _approve(engine, legs)
    _record(svc, "m-1", "1-0", "o:1")
    _record(svc, "m-2", "3-1", "o:2")
    _settle(svc, ticket, "m-1", "s:1")
    # stake 60, payout 60 × 2.0 × 1.5 = 180 → ledger -60 + 180 = +120
    assert ledger_balance(engine) == pytest.approx(120.0)


def test_legacy_null_odds_leg_settles_under_placeholder_method(tmp_path: Path) -> None:
    engine, svc, fr = _setup(tmp_path)
    ticket = _approve(engine, [_leg("m-1", fr["m-1"], 1.80)])
    # simulate a pre-migration-9 leg: NULL entry_odds on disk
    with OntologyUnitOfWork(engine) as uow:
        uow.connection.execute(text("UPDATE bet_legs SET entry_odds = NULL"))
    _record(svc, "m-1", "2-0", "o:1")
    _settle(svc, ticket, "m-1", "s:1")
    with OntologyUnitOfWork(engine) as uow:
        method = uow.connection.execute(
            select(sf.ticket_settlements.c.settlement_method_version)).scalar_one()
        assert method == "had-3way-v1"                                 # auditable legacy path
        assert ledger_balance(engine) == 100.0        # flat ×2 placeholder

