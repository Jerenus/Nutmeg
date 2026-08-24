import json

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app

from .conftest import CLOCK


@pytest.fixture
def client(product_services) -> TestClient:
    return TestClient(
        create_product_app(
            product_services,
            session_secret="test-session-secret",
            csrf_secret="test-csrf-secret",
            clock=lambda: CLOCK,
        )
    )


def _session(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    assert response.status_code == 200
    assert response.headers["set-cookie"].lower().find("httponly") >= 0
    assert "samesite=strict" in response.headers["set-cookie"].lower()
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def _action_payload() -> dict[str, object]:
    return {
        "action_type": "record_adjudication",
        "idempotency_key": "api:adjudication:1",
        "payload": {
            "actor_id": "attacker",
            "actor_role": "ai_analyst",
            "subject_type": "claim",
            "subject_id": "claim-before",
            "decision": "hold",
            "reason": "await verified lineup",
            "evidence_rejected": [],
            "alternative": {},
        },
        "expected_versions": {},
    }


def test_query_routes_publish_v1_contract(client: TestClient) -> None:
    health = client.get("/api/v1/system/health")
    board = client.get("/api/v1/board?date=2026-08-24")
    match = client.get("/api/v1/matches/match-1")

    assert health.status_code == 200
    assert health.json()["schema_version"] == "1"
    assert board.status_code == 200
    assert board.json()["schema_version"] == "1"
    assert match.status_code == 200
    assert match.json()["schema_version"] == "1"


def test_mutation_requires_session_csrf_and_same_origin(client: TestClient) -> None:
    payload = _action_payload()
    assert client.post("/api/v1/actions", json=payload).status_code == 403

    headers = _session(client)
    evil = client.post(
        "/api/v1/actions",
        json=payload,
        headers={**headers, "Origin": "https://evil.example"},
    )
    committed = client.post("/api/v1/actions", json=payload, headers=headers)

    assert evil.status_code == 403
    assert committed.status_code == 200
    assert committed.json()["status"] == "committed"


def test_error_envelope_is_stable(client: TestClient) -> None:
    response = client.get("/api/v1/matches/absent")

    assert response.status_code == 404
    assert response.json() == {
        "code": "object_not_found",
        "message": "match absent not found",
        "action_id": None,
        "field_errors": {},
        "retryable": False,
        "current_version": None,
        "details": {},
    }


def test_events_resume_after_cursor(client: TestClient) -> None:
    first = client.get("/api/v1/events?after=0&limit=1").json()
    second = client.get(
        f"/api/v1/events?after={first['next_cursor']}&limit=20"
    ).json()

    assert first["items"]
    assert all(
        event["sequence"] > first["next_cursor"] for event in second["items"]
    )


def test_sse_once_encodes_durable_event_batch(client: TestClient) -> None:
    response = client.get("/api/v1/events/stream?after=0&once=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    lines = response.text.splitlines()
    assert any(line.startswith("id: ") for line in lines)
    assert any(line.startswith("event: action.committed") for line in lines)
    data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
    assert json.loads(data)["sequence"] >= 1
