from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app

from .conftest import CLOCK


@pytest.fixture
def client(m2_product_services) -> TestClient:
    return TestClient(
        create_product_app(
            m2_product_services,
            session_secret="m2-test-session-secret",
            csrf_secret="m2-test-csrf-secret",
            clock=lambda: CLOCK,
        )
    )


def _session(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    assert response.status_code == 200
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def _merge_action_payload() -> dict[str, object]:
    return {
        "action_type": "merge_entity",
        "idempotency_key": "api:merge:1",
        "payload": {
            "entity_type": "team",
            "from_id": "team-duplicate",
            "into_id": "team-home",
            "reason": "same provider-backed club",
            "actor_id": "attacker",
            "actor_role": "judge_operator",
        },
        "expected_versions": {},
    }


def test_m2_query_endpoints_publish_v1_contract(client: TestClient) -> None:
    command = client.get("/api/v1/command-center?date=2026-08-24&q=Home")
    operations = client.get("/api/v1/operations")
    alerts = client.get("/api/v1/alerts")
    identities = client.get("/api/v1/identities?limit=50")

    assert all(
        response.status_code == 200
        for response in (command, operations, alerts, identities)
    )
    assert command.json()["schema_version"] == "1"
    assert operations.json()["schema_version"] == "1"
    assert alerts.json()
    assert identities.json()[0]["entity_id"] == "team-duplicate"
    as_of = datetime.fromisoformat(
        command.json()["board"]["as_of"].replace("Z", "+00:00")
    )
    assert as_of.utcoffset() is not None


def test_board_keeps_contract_while_accepting_m2_filters(client: TestClient) -> None:
    response = client.get(
        "/api/v1/board?date=2026-08-24&readiness=ready&q=Home"
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1"
    assert [item["match_id"] for item in response.json()["matches"]] == ["match-1"]


def test_invalid_filter_and_naive_as_of_use_standard_422_envelope(
    client: TestClient,
) -> None:
    invalid_readiness = client.get(
        "/api/v1/command-center?date=2026-08-24&readiness=unknown"
    )
    naive_as_of = client.get(
        "/api/v1/operations?as_of=2026-08-24T10:00:00"
    )

    assert invalid_readiness.status_code == 422
    assert invalid_readiness.json()["code"] == "validation_error"
    assert naive_as_of.status_code == 422
    assert naive_as_of.json()["code"] == "validation_error"


def test_identity_merge_still_requires_session_csrf_and_same_origin(
    client: TestClient,
) -> None:
    payload = _merge_action_payload()
    assert client.post("/api/v1/actions", json=payload).status_code == 403

    headers = _session(client)
    committed = client.post("/api/v1/actions", json=payload, headers=headers)

    assert committed.status_code == 200
    assert committed.json()["status"] == "committed"
