import importlib
import inspect
import pkgutil

from fastapi.testclient import TestClient

import nutmeg.product
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.wiring import build_product_services

from .conftest import CLOCK


def _session(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def _forecast_action(match_id: str) -> dict[str, object]:
    return {
        "action_type": "commit_forecast",
        "idempotency_key": "golden:forecast:1",
        "payload": {
            "match_id": match_id,
            "market_definition_id": "md-had",
            "cutoff_at": "2026-08-24T10:00:00+00:00",
            "belief_distribution": {"home": 0.52, "draw": 0.28, "away": 0.2},
            "factors": [],
            "commitment_tier": "judged",
            "falsifier": "official lineup contradicts availability",
        },
        "expected_versions": {f"forecast:{match_id}:md-had": 1},
    }


def test_m1_golden_day_from_board_to_forecast_lineage_and_restart(
    product_services,
) -> None:
    client = TestClient(create_product_app(product_services, clock=lambda: CLOCK))
    board = client.get("/api/v1/board?date=2026-08-24").json()
    match = board["matches"][0]
    assert match["readiness"]["level"] == "ready"

    detail = client.get(
        f"/api/v1/matches/{match['match_id']}?as_of=2026-08-24T10:00:00Z"
    ).json()
    assert detail["evidence"]["observations"]
    assert all(
        item["recorded_at"] <= "2026-08-24T10:00:00+00:00"
        for item in detail["evidence"]["observations"]
    )

    action_payload = _forecast_action(match["match_id"])
    committed = client.post(
        "/api/v1/actions", headers=_session(client), json=action_payload
    )
    assert committed.status_code == 200
    revision_id = committed.json()["result_refs"][0]["object_id"]
    action_id = committed.json()["action_id"]

    lineage = client.get(
        f"/api/v1/lineage/forecast_revision/{revision_id}"
    ).json()
    assert {edge["relation"] for edge in lineage["edges"]} >= {
        "forecast_for_match",
        "forecast_uses_bundle",
    }
    events = client.get("/api/v1/events?after=0&limit=100").json()
    assert any(item["object_id"] == revision_id for item in events["items"])
    cursor = events["next_cursor"]

    restarted_services = build_product_services(product_services.settings)
    restarted = TestClient(
        create_product_app(restarted_services, clock=lambda: CLOCK)
    )
    replayed = restarted.post(
        "/api/v1/actions", headers=_session(restarted), json=action_payload
    )

    assert replayed.status_code == 200
    assert replayed.json()["action_id"] == action_id
    assert replayed.json()["result_refs"][0]["object_id"] == revision_id
    with OntologyUnitOfWork(restarted_services.kernel.engine) as uow:
        series_id = uow.decision.ensure_series(match["match_id"], "md-had")
        assert uow.decision.max_revision_no(series_id) == 2
        assert uow.decision.count_committed_revisions() == 1
    resumed = restarted.get(f"/api/v1/events?after={cursor}&limit=100").json()
    assert resumed["items"] == []
    assert resumed["next_cursor"] == cursor


def test_product_runtime_has_no_legacy_decision_store_dependency() -> None:
    modules = [nutmeg.product]
    modules.extend(
        importlib.import_module(name)
        for _, name, _ in pkgutil.walk_packages(
            nutmeg.product.__path__, prefix="nutmeg.product."
        )
    )
    modules.append(importlib.import_module("nutmeg.interfaces.product_api"))

    source = "\n".join(inspect.getsource(module) for module in modules)

    assert "nutmeg.decision.store" not in source
    assert "nutmeg.decision.workbench" not in source
