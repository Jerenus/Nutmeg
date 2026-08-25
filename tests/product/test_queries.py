from datetime import date

import pytest

from nutmeg.product.contracts import ReadinessLevel
from nutmeg.product.errors import ProductNotFoundError

from .conftest import CLOCK


def test_board_returns_named_match_and_explicit_readiness(product_services) -> None:
    board = product_services.queries.board(date(2026, 8, 24), as_of=CLOCK)

    assert board.matches[0].home_team == "Home FC"
    assert board.matches[0].away_team == "Away FC"
    assert board.matches[0].kickoff_at == "2026-08-24T12:00:00+00:00"
    assert board.matches[0].readiness.level is ReadinessLevel.READY


def test_match_as_of_excludes_future_data(product_services) -> None:
    detail = product_services.queries.match("match-1", as_of=CLOCK)

    assert detail.market_snapshot is not None
    assert detail.market_snapshot.market_snapshot_id == "snapshot-before"
    assert {item.observation_id for item in detail.evidence.observations} == {
        "obs-before"
    }
    assert {item.claim_id for item in detail.evidence.claims} == {"claim-before"}


def test_legacy_forecast_is_never_presented_as_bundled(product_services) -> None:
    detail = product_services.queries.match("match-1", as_of=CLOCK)

    assert detail.forecasts[0].forecast_revision_id == "fr-legacy"
    assert detail.forecasts[0].evidence_status == "legacy_unbundled"


def test_lineage_action_event_and_health_queries_are_stable(product_services) -> None:
    lineage = product_services.queries.lineage("forecast_revision", "fr-legacy")

    assert any(edge.relation == "forecast_for_match" for edge in lineage.edges)
    first_actions = product_services.queries.actions(limit=1)
    second_actions = product_services.queries.actions(
        after=first_actions.next_cursor, limit=20
    )
    assert first_actions.items
    assert second_actions.items
    assert not ({item.action_id for item in first_actions.items} & {
        item.action_id for item in second_actions.items
    })
    events = product_services.queries.events(after=0, limit=20)
    assert events.items
    assert events.next_cursor == events.items[-1].sequence
    health = product_services.queries.health()
    assert health.integrity_check == "ok"
    assert health.outbox_event_count == 2


def test_absent_product_object_raises_stable_not_found(product_services) -> None:
    with pytest.raises(ProductNotFoundError, match="match absent not found"):
        product_services.queries.match("absent", as_of=CLOCK)
