from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.errors import IdempotencyConflictError
from nutmeg.product.contracts import (
    IssueConfirmationResponse,
    ObjectRefContract,
    ProductActionResponse,
)
from nutmeg.product.errors import ProductNotFoundError, ProductTicketError

from .conftest import CLOCK


class _ApiQueries:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def ticket_workbench(self, day: date, *, as_of):
        return {
            "schema_version": "1",
            "date": day.isoformat(),
            "as_of": as_of.isoformat(),
            "matches": [],
            "batch_revisions": [],
        }

    def ticket_batch(self, ticket_batch_id: str):
        if ticket_batch_id == "absent":
            raise ProductNotFoundError("ticket batch absent not found")
        return {
            "schema_version": "1",
            "ticket_batch_id": ticket_batch_id,
            "revisions": [],
        }

    def ticket_artifact(self, ticket_artifact_id: str, *, as_of=None):
        return {
            "schema_version": "1",
            "ticket_artifact_id": ticket_artifact_id,
            "ticket_hash": "a" * 64,
            "amount": 100.0,
            "deadline_at": "2026-08-24T12:00:00Z",
            "placement_state": "unplaced",
        }


class _ApiTickets:
    def __init__(self, error: Exception | None = None, *, rejected: bool = False) -> None:
        self.error = error
        self.rejected = rejected
        self.calls: list[tuple[str, str | None, object]] = []

    def _response(self, action_type: str) -> ProductActionResponse:
        if self.error is not None:
            raise self.error
        return ProductActionResponse(
            action_id=f"action-{action_type}",
            action_type=action_type,
            status="rejected" if self.rejected else "committed",
            result_refs=(
                []
                if self.rejected
                else [
                    ObjectRefContract(object_type="ticket", object_id="ticket-1"),
                    ObjectRefContract(
                        object_type="cash_transaction", object_id="cash-1"
                    ),
                ]
            ),
            error_code="permission_denied" if self.rejected else None,
            error_detail="judge permission is required" if self.rejected else None,
            committed_at=CLOCK.isoformat(),
        )

    def create_batch(self, command):
        self.calls.append(("create", None, command))
        return self._response("create_ticket_batch")

    def remove_leg(self, ticket_batch_id: str, command):
        self.calls.append(("remove", ticket_batch_id, command))
        return self._response("remove_ticket_leg")

    def approve_batch(self, ticket_batch_id: str, command):
        self.calls.append(("approve", ticket_batch_id, command))
        return self._response("approve_ticket_batch")

    def issue_confirmation(self, ticket_artifact_id: str, command):
        self.calls.append(("issue", ticket_artifact_id, command))
        response = self._response("issue_ticket_confirmation")
        return IssueConfirmationResponse(
            **response.model_dump(mode="python"),
            confirmation_id="confirmation-1",
            nonce="nonce-plaintext-once",
            expires_at="2026-08-24T10:05:00+00:00",
        )

    def confirm_placement(self, ticket_artifact_id: str, command):
        self.calls.append(("confirm", ticket_artifact_id, command))
        if command.receipt_base64 is None or command.receipt_content_type is None:
            raise ProductTicketError(
                "receipt_required",
                "manual receipt and content type are required",
                status_code=422,
            )
        return self._response("confirm_ticket_placement")


def _client(m3_product_services, tickets=None) -> TestClient:
    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=_ApiQueries(m3_product_services.queries),
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=None,
        tickets=tickets or _ApiTickets(),
    )
    return TestClient(
        create_product_app(
            services,
            session_secret="m4-api-session-secret",
            csrf_secret="m4-api-csrf-secret",
            clock=lambda: CLOCK,
        )
    )


@pytest.fixture
def client(m3_product_services) -> TestClient:
    return _client(m3_product_services)


def _session(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    assert response.status_code == 200
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def _leg() -> dict[str, object]:
    return {
        "leg_key": "match-1:md-had:home",
        "match_id": "match-1",
        "match_no": 1,
        "name": "Home FC - Away FC",
        "market_definition_id": "md-had",
        "selection_id": "sel-had-home",
        "outcome_key": "home",
        "faces": "3",
        "forecast_revision_id": "fr-current",
        "entry_quote_id": "quote-home",
        "odds": 2.1,
        "line": None,
        "bucket": "main",
        "fair": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "confidence": 4,
        "directional_flags": [],
        "nondirectional_flags": [],
        "anchor_integrity": "pass",
        "precedents": [],
    }


def _create() -> dict[str, object]:
    return {
        "schema_version": "1",
        "run_date": "2026-08-24",
        "channel": "jczq",
        "account_id": "acct-jczq",
        "currency": "CNY",
        "deadline_at": "2026-08-24T12:00:00Z",
        "legs": [_leg()],
        "idempotency_key": "m4:api:create",
    }


def _confirm() -> dict[str, object]:
    return {
        "schema_version": "1",
        "confirmation_id": "confirmation-1",
        "nonce": "nonce-plaintext-once",
        "ticket_hash": "a" * 64,
        "amount": 100.0,
        "currency": "CNY",
        "channel": "jczq",
        "placement_mode": "manual",
        "external_reference": "manual-001",
        "receipt_base64": "cmVjZWlwdA==",
        "receipt_content_type": "text/plain",
        "idempotency_key": "m4:api:confirm",
    }


POST_CASES = (
    ("/api/v1/ticket-batches", _create()),
    (
        "/api/v1/ticket-batches/batch-1/remove-leg",
        {
            "schema_version": "1",
            "leg_key": "match-1:md-had:home",
            "expected_revision_no": 1,
            "idempotency_key": "m4:api:remove",
        },
    ),
    (
        "/api/v1/ticket-batches/batch-1/approve",
        {
            "schema_version": "1",
            "expected_revision_no": 1,
            "idempotency_key": "m4:api:approve",
        },
    ),
    (
        "/api/v1/ticket-artifacts/artifact-1/confirmations",
        {"schema_version": "1", "idempotency_key": "m4:api:issue"},
    ),
    ("/api/v1/ticket-artifacts/artifact-1/confirm", _confirm()),
)


def test_m4_get_routes_remain_published_and_legacy_posts_are_retired(
    client: TestClient,
) -> None:
    headers = _session(client)
    gets = (
        client.get(
            "/api/v1/ticket-workbench?date=2026-08-24&as_of=2026-08-24T10:00:00Z"
        ),
        client.get("/api/v1/ticket-batches/batch-1"),
        client.get("/api/v1/ticket-artifacts/artifact-1"),
    )
    posts = [client.post(path, json=body, headers=headers) for path, body in POST_CASES]

    assert all(response.status_code == 200 for response in gets)
    assert all(response.status_code == 405 for response in posts)
    assert gets[0].json()["schema_version"] == "1"
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/api/v1/ticket-workbench",
        "/api/v1/ticket-batches/{ticket_batch_id}",
        "/api/v1/ticket-artifacts/{ticket_artifact_id}",
        "/api/v1/ticket-batches",
        "/api/v1/ticket-batches/{ticket_batch_id}/remove-leg",
        "/api/v1/ticket-batches/{ticket_batch_id}/approve",
        "/api/v1/ticket-artifacts/{ticket_artifact_id}/confirmations",
        "/api/v1/ticket-artifacts/{ticket_artifact_id}/confirm",
    } <= paths.keys()


@pytest.mark.parametrize(("path", "body"), POST_CASES)
def test_every_m4_mutation_is_retired_before_session_or_body_parsing(
    client: TestClient, path: str, body: dict[str, object]
) -> None:
    assert client.post(path, json=body).status_code == 405
    assert client.post(
        path,
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    ).status_code == 405
    headers = _session(client)
    assert (
        client.post(path, json=body, headers={"Origin": headers["Origin"]}).status_code
        == 405
    )
    assert (
        client.post(
            path,
            json=body,
            headers={**headers, "Origin": "https://evil.example"},
        ).status_code
        == 405
    )
    assert client.post(path, json=body, headers=headers).status_code == 405


def test_actor_spoofing_cannot_reach_retired_ticket_route(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ticket-batches",
        json={**_create(), "actor_id": "attacker", "actor_role": "ai_analyst"},
        headers=_session(client),
    )

    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


@pytest.mark.parametrize(
    ("status", "code"),
    (
        (409, "ticket_audit_blocked"),
        (409, "ticket_warning_unadjudicated"),
        (409, "ticket_revision_conflict"),
        (409, "ticket_deadline_passed"),
        (409, "confirmation_stale"),
        (409, "confirmation_reused"),
        (409, "confirmation_binding_mismatch"),
        (409, "ticket_already_placed"),
        (422, "receipt_required"),
        (503, "connector_unavailable"),
    ),
)
def test_retired_ticket_routes_do_not_invoke_ticket_services(
    m3_product_services, status: int, code: str
) -> None:
    tickets = _ApiTickets(ProductTicketError(code, f"fixture {code}", status_code=status))
    client = _client(m3_product_services, tickets)

    response = client.post(
        "/api/v1/ticket-batches/batch-1/approve",
        json={
            "schema_version": "1",
            "expected_revision_no": 1,
            "idempotency_key": f"m4:api:error:{code}",
        },
        headers=_session(client),
    )

    assert response.status_code == 405
    assert tickets.calls == []


def test_get_not_found_remains_stable_while_legacy_mutations_are_retired(
    m3_product_services,
) -> None:
    missing = _client(m3_product_services).get("/api/v1/ticket-batches/absent")
    conflict_client = _client(
        m3_product_services, _ApiTickets(IdempotencyConflictError("key reused"))
    )
    conflict = conflict_client.post(
        "/api/v1/ticket-batches/batch-1/approve",
        json={
            "schema_version": "1",
            "expected_revision_no": 1,
            "idempotency_key": "m4:api:conflict",
        },
        headers=_session(conflict_client),
    )
    denied_client = _client(m3_product_services, _ApiTickets(rejected=True))
    denied = denied_client.post(
        "/api/v1/ticket-batches/batch-1/approve",
        json={
            "schema_version": "1",
            "expected_revision_no": 1,
            "idempotency_key": "m4:api:denied",
        },
        headers=_session(denied_client),
    )
    receipt_client = _client(m3_product_services)
    without_receipt = _confirm()
    without_receipt.pop("receipt_base64")
    receipt = receipt_client.post(
        "/api/v1/ticket-artifacts/artifact-1/confirm",
        json=without_receipt,
        headers=_session(receipt_client),
    )

    assert missing.status_code == 404
    assert missing.json()["code"] == "object_not_found"
    assert conflict.status_code == 405
    assert denied.status_code == 405
    assert receipt.status_code == 405


def test_blocked_nonce_and_receipt_never_reach_action_or_event_feeds(
    client: TestClient,
) -> None:
    headers = _session(client)
    issued = client.post(
        "/api/v1/ticket-artifacts/artifact-1/confirmations",
        json={"schema_version": "1", "idempotency_key": "m4:api:issue:leak"},
        headers=headers,
    )
    confirmed = client.post(
        "/api/v1/ticket-artifacts/artifact-1/confirm",
        json={**_confirm(), "idempotency_key": "m4:api:confirm:leak"},
        headers=headers,
    )
    actions = client.get("/api/v1/actions?limit=500")
    events = client.get("/api/v1/events?after=0&limit=500")

    assert issued.status_code == 405
    assert confirmed.status_code == 405
    for feed in (actions.text, events.text):
        assert "nonce-plaintext-once" not in feed
        assert "cmVjZWlwdA==" not in feed
