from datetime import UTC, datetime
from pathlib import Path

from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.market.models import QuoteInput, SnapshotBuildRequest
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _actions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.identity.insert_match_minimal("match-1")
    return MarketActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def test_build_snapshot_devigs_had_from_quotes(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    quotes = [
        QuoteInput(market_definition_id="md-had", selection_id="sel-had-home", decimal_odds=2.0),
        QuoteInput(market_definition_id="md-had", selection_id="sel-had-draw", decimal_odds=3.5),
        QuoteInput(market_definition_id="md-had", selection_id="sel-had-away", decimal_odds=4.0),
    ]
    outcome = actions.build_snapshot(SnapshotBuildRequest(
        match_id="match-1", market_definition_id="md-had", snapshot_kind="read_time",
        as_of="2026-07-19T15:00:00+08:00", provider="sporttery", quotes=quotes,
        actor_id="system:devig", actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        idempotency_key="snap:1", requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        fair = uow.market.latest_fair("match-1", "md-had")
        assert abs(sum(fair.values()) - 1.0) < 1e-9
        assert fair["home"] > fair["away"]
        assert uow.market.count_quotes() == 3


def test_ai_analyst_cannot_build_snapshot(tmp_path: Path) -> None:
    actions, _engine = _actions(tmp_path)
    outcome = actions.build_snapshot(SnapshotBuildRequest(
        match_id="match-1", market_definition_id="md-had", snapshot_kind="read_time",
        as_of="2026-07-19T15:00:00+08:00", provider="sporttery",
        quotes=[QuoteInput(
            market_definition_id="md-had", selection_id="sel-had-home", decimal_odds=2.0
        )],
        actor_id="model:x", actor_role=ActorRole.AI_ANALYST,
        idempotency_key="snap:denied", requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
    ))
    assert outcome.status is ActionStatus.REJECTED
