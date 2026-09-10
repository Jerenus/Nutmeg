from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.contracts import CopilotDraft
from nutmeg.product.copilot import (
    MatchCopilotService,
    ProductCopilotUnavailableError,
)

from .conftest import CLOCK


class ApiCopilotProvider:
    model_name = "api-fixture-copilot"
    model_version = "fixture-v1"

    def investigate(self, context: dict[str, object]) -> CopilotDraft:
        return CopilotDraft(
            summary="Availability remains unresolved.",
            scenarios=[],
            proposed_belief={"home": 0.48, "draw": 0.31, "away": 0.21},
            factors=[],
            falsifier="The official lineup restores the player.",
            citations=[{"object_type": "claim", "object_id": "claim-before"}],
            conflicts=["availability_risk"],
            missing_evidence=["official lineup"],
        )


@pytest.fixture
def client(m3_product_services) -> TestClient:
    copilot = MatchCopilotService(
        queries=m3_product_services.queries,
        actions=m3_product_services.actions,
        provider=ApiCopilotProvider(),
    )
    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=m3_product_services.queries,
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=copilot,
    )
    return TestClient(
        create_product_app(
            services,
            session_secret="m3-api-session-secret",
            csrf_secret="m3-api-csrf-secret",
            clock=lambda: CLOCK,
        )
    )


@pytest.fixture
def disabled_client(m3_product_services) -> TestClient:
    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=m3_product_services.queries,
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=None,
    )
    return TestClient(
        create_product_app(
            services,
            session_secret="m3-disabled-session-secret",
            csrf_secret="m3-disabled-csrf-secret",
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


def _request(key: str = "copilot:api:first") -> dict[str, object]:
    return {
        "schema_version": "1",
        "idempotency_key": key,
        "prompt": "Compare the lineup claims.",
        "as_of": "2026-08-24T10:00:00Z",
    }


def test_legacy_copilot_route_is_retired_before_session_or_body_parsing(
    client: TestClient,
) -> None:
    body = _request()
    before = client.get("/api/v1/actions?limit=500").json()["items"]
    assert client.post(
        "/api/v1/matches/match-1/copilot",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    ).status_code == 405
    headers = _session(client)
    evil = client.post(
        "/api/v1/matches/match-1/copilot",
        headers={**headers, "Origin": "https://evil.example"},
        json=body,
    )
    retired = client.post(
        "/api/v1/matches/match-1/copilot", headers=headers, json=body
    )

    assert evil.status_code == 405
    assert retired.status_code == 405
    assert client.get("/api/v1/actions?limit=500").json()["items"] == before


def test_unavailable_copilot_is_explicit_not_internal_error(
    disabled_client: TestClient,
) -> None:
    response = disabled_client.post(
        "/api/v1/matches/match-1/copilot",
        headers=_session(disabled_client),
        json=_request("copilot:api:disabled"),
    )

    assert response.status_code == 405


def test_invalid_copilot_response_uses_stable_422_without_provider_body(
    m3_product_services,
) -> None:
    class InvalidProvider:
        model_name = "invalid-fixture-copilot"
        model_version = "fixture-v1"

        def investigate(self, context: dict[str, object]) -> dict[str, object]:
            return {
                "summary": "SECRET-PROVIDER-BODY",
                "scenarios": [],
                "proposed_belief": None,
                "factors": [],
                "falsifier": None,
                "citations": [],
                "conflicts": [],
                "missing_evidence": [],
                "actor_role": "judge_operator",
            }

    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=m3_product_services.queries,
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=MatchCopilotService(
            queries=m3_product_services.queries,
            actions=m3_product_services.actions,
            provider=InvalidProvider(),  # type: ignore[arg-type]
        ),
    )
    invalid_client = TestClient(
        create_product_app(
            services,
            session_secret="m3-invalid-session-secret",
            csrf_secret="m3-invalid-csrf-secret",
            clock=lambda: CLOCK,
        )
    )

    response = invalid_client.post(
        "/api/v1/matches/match-1/copilot",
        headers=_session(invalid_client),
        json=_request("copilot:api:invalid"),
    )

    assert response.status_code == 405
    assert "SECRET-PROVIDER-BODY" not in response.text


def test_match_api_returns_temporal_investigation(client: TestClient) -> None:
    response = client.get(
        "/api/v1/matches/match-1?as_of=2026-08-24T10:00:00Z"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["market_timeline"]
    assert payload["evidence"]["conflicts"]
    assert "obs-future" not in response.text
    assert "snapshot-future" not in response.text


def test_copilot_rejects_actor_and_action_spoofing_before_write(
    client: TestClient,
) -> None:
    before = client.get("/api/v1/actions?limit=500").json()["items"]
    body = {
        **_request("copilot:api:spoof"),
        "actor_id": "attacker",
        "actor_role": "judge_operator",
        "action_type": "commit_forecast",
        "policy_version": "attacker-policy",
    }

    response = client.post(
        "/api/v1/matches/match-1/copilot",
        headers=_session(client),
        json=body,
    )

    assert response.status_code == 405
    after = client.get("/api/v1/actions?limit=500").json()["items"]
    assert len(after) == len(before)


def test_transient_provider_failure_uses_redacted_503(m3_product_services) -> None:
    class OfflineProvider:
        model_name = "offline-fixture-copilot"
        model_version = "fixture-v1"

        def investigate(self, context: dict[str, object]) -> CopilotDraft:
            raise ProductCopilotUnavailableError("SECRET-UPSTREAM-DETAIL")

    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=m3_product_services.queries,
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=MatchCopilotService(
            queries=m3_product_services.queries,
            actions=m3_product_services.actions,
            provider=OfflineProvider(),
        ),
    )
    offline_client = TestClient(
        create_product_app(
            services,
            session_secret="m3-offline-session-secret",
            csrf_secret="m3-offline-csrf-secret",
            clock=lambda: CLOCK,
        )
    )

    response = offline_client.post(
        "/api/v1/matches/match-1/copilot",
        headers=_session(offline_client),
        json=_request("copilot:api:offline"),
    )

    assert response.status_code == 405
    assert "SECRET-UPSTREAM-DETAIL" not in response.text
