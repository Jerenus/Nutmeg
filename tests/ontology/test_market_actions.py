from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.market_actions import MarketActions
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import IdempotencyConflictError
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


def test_hhad_snapshot_persists_one_signed_line_on_every_quote(tmp_path: Path) -> None:
    actions, engine = _actions(tmp_path)
    quotes = [
        QuoteInput(
            market_definition_id="md-hhad",
            selection_id=f"sel-hhad-{face}",
            decimal_odds=odds,
            settlement_parameter_decimal="-1.000000000000",
        )
        for face, odds in (("home", 2.1), ("draw", 3.4), ("away", 3.1))
    ]

    outcome = actions.build_snapshot(
        SnapshotBuildRequest(
            match_id="match-1",
            market_definition_id="md-hhad",
            snapshot_kind="read_time",
            as_of="2026-07-19T15:00:00+08:00",
            provider="sporttery",
            quotes=quotes,
            actor_id="system:devig",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="snap:hhad:1",
            requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
        )
    )

    assert outcome.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        lines = {
            uow.market.quote(quote_id).settlement_parameter_decimal
            for quote_id in uow.market.snapshot_quote_ids(
                outcome.result_refs[0].object_id
            )
        }
    assert lines == {"-1.000000000000"}


@pytest.mark.parametrize("changed_field", ("odds", "line"))
def test_snapshot_idempotency_hash_covers_exact_quote_content(
    tmp_path: Path,
    changed_field: str,
) -> None:
    actions, _engine = _actions(tmp_path)

    def request(*, home_odds: float, line: str) -> SnapshotBuildRequest:
        return SnapshotBuildRequest(
            match_id="match-1",
            market_definition_id="md-hhad",
            snapshot_kind="read_time",
            as_of="2026-07-19T15:00:00+08:00",
            provider="sporttery",
            quotes=[
                QuoteInput(
                    market_definition_id="md-hhad",
                    selection_id=f"sel-hhad-{face}",
                    decimal_odds=home_odds if face == "home" else odds,
                    bookmaker="sporttery",
                    settlement_parameter_decimal=line,
                )
                for face, odds in (("home", 2.1), ("draw", 3.4), ("away", 3.1))
            ],
            actor_id="system:devig",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="snap:hhad:exact-input",
            requested_at=datetime(2026, 7, 19, 8, tzinfo=UTC),
            artifact_retrieval_id=None,
        )

    first = request(home_odds=2.1, line="-1.000000000000")
    changed = request(
        home_odds=2.2 if changed_field == "odds" else 2.1,
        line="-2.000000000000" if changed_field == "line" else "-1.000000000000",
    )
    assert actions.build_snapshot(first).status is ActionStatus.COMMITTED

    with pytest.raises(IdempotencyConflictError):
        actions.build_snapshot(changed)
