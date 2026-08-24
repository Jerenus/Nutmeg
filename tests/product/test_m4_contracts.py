import base64
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from nutmeg.ontology.actions.models import (
    ActionOutcome,
    ActionStatus,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.protected_ticket_actions import ConfirmationIssueResult
from nutmeg.product.contracts import (
    ApproveTicketBatchCommand,
    ConfirmPlacementCommand,
    CreateTicketBatchCommand,
    IssueConfirmationCommand,
    RemoveTicketLegCommand,
    TicketLegCommand,
)
from nutmeg.product.errors import ProductTicketError
from nutmeg.product.tickets import (
    ConnectorPlacementReceipt,
    ProductTicketService,
)

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)
DEADLINE = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _leg() -> TicketLegCommand:
    return TicketLegCommand(
        leg_key="match-1:md-had:home",
        match_id="match-1",
        match_no=1,
        name="Home FC - Away FC",
        market_definition_id="md-had",
        selection_id="sel-had-home",
        outcome_key="home",
        faces="3",
        forecast_revision_id="fr-current",
        entry_quote_id="quote-home",
        odds=2.1,
        line=None,
        bucket="main",
        fair={"home": 0.6, "draw": 0.25, "away": 0.15},
        confidence=4,
        directional_flags=[],
        nondirectional_flags=[],
        anchor_integrity="pass",
        precedents=[],
    )


def _create_payload() -> dict[str, object]:
    return {
        "run_date": date(2026, 8, 24),
        "channel": "jczq",
        "account_id": "acct-jczq",
        "currency": "CNY",
        "deadline_at": DEADLINE,
        "legs": [_leg().model_dump(mode="python")],
        "idempotency_key": "m4:create:1",
    }


def test_m4_mutation_contracts_are_strict_and_server_owned() -> None:
    command = CreateTicketBatchCommand(**_create_payload())

    assert command.schema_version == "1"
    assert command.legs[0].forecast_revision_id == "fr-current"

    spoofed = _create_payload()
    spoofed["actor_role"] = "ai_analyst"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CreateTicketBatchCommand(**spoofed)

    naive = _create_payload()
    naive["deadline_at"] = datetime(2026, 8, 24, 12)
    with pytest.raises(ValidationError, match="timezone"):
        CreateTicketBatchCommand(**naive)

    with pytest.raises(ValidationError, match="greater_than_equal"):
        RemoveTicketLegCommand(
            leg_key="match-1:md-had:home",
            expected_revision_no=-1,
            idempotency_key="m4:remove:invalid",
        )

    with pytest.raises(ValidationError, match="greater_than_equal"):
        ApproveTicketBatchCommand(
            expected_revision_no=0,
            idempotency_key="m4:approve:invalid",
        )


def test_confirmation_contract_rejects_invalid_base64_and_sub_fen_amounts() -> None:
    values: dict[str, object] = {
        "confirmation_id": "confirmation-1",
        "nonce": "nonce-once",
        "ticket_hash": "a" * 64,
        "amount": 100.0,
        "currency": "CNY",
        "channel": "jczq",
        "placement_mode": "manual",
        "external_reference": "manual-001",
        "receipt_base64": base64.b64encode(b"receipt fixture").decode("ascii"),
        "receipt_content_type": "text/plain",
        "idempotency_key": "m4:confirm:1",
    }
    command = ConfirmPlacementCommand(**values)
    assert command.amount == 100.0

    with pytest.raises(ValidationError, match="valid base64"):
        ConfirmPlacementCommand(**{**values, "receipt_base64": "%%%"})

    with pytest.raises(ValidationError, match="whole fen"):
        ConfirmPlacementCommand(**{**values, "amount": 100.001})


class _ProtectedTicketSpy:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def create_ticket_batch(self, request):
        self.requests.append(request)
        return _outcome("create_ticket_batch")

    def issue_ticket_confirmation(self, request):
        self.requests.append(request)
        return ConfirmationIssueResult(
            outcome=_outcome("issue_ticket_confirmation"),
            confirmation_id="confirmation-1",
            nonce="nonce-once",
            expires_at="2026-08-24T10:05:00+00:00",
        )

    def confirm_ticket_placement(self, request):
        self.requests.append(request)
        return _outcome("confirm_ticket_placement")


class _FakeConnector:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def place(self, request):
        self.requests.append(request)
        return ConnectorPlacementReceipt(
            external_reference="connector-order-001",
            receipt_content=b"fake connector receipt",
            receipt_content_type="application/json",
        )


def _outcome(action_type: str) -> ActionOutcome:
    return ActionOutcome(
        action_id=f"action-{action_type}",
        action_type=action_type,
        status=ActionStatus.COMMITTED,
        result_refs=(ObjectRef("fixture", "fixture-1"),),
        committed_at=AT.isoformat(),
    )


def test_product_ticket_service_assigns_human_actor_and_decodes_receipt() -> None:
    actions = _ProtectedTicketSpy()
    service = ProductTicketService(
        actions,
        actor_id="operator:owner",
        clock=lambda: AT,
    )

    created = service.create_batch(CreateTicketBatchCommand(**_create_payload()))
    issued = service.issue_confirmation(
        "ticket-artifact-1",
        IssueConfirmationCommand(idempotency_key="m4:issue:1"),
    )
    receipt = b"receipt fixture"
    confirmed = service.confirm_placement(
        "ticket-artifact-1",
        ConfirmPlacementCommand(
            confirmation_id="confirmation-1",
            nonce="nonce-once",
            ticket_hash="a" * 64,
            amount=100.0,
            currency="CNY",
            channel="jczq",
            placement_mode="manual",
            external_reference="manual-001",
            receipt_base64=base64.b64encode(receipt).decode("ascii"),
            receipt_content_type="text/plain",
            idempotency_key="m4:confirm:1",
        ),
    )

    assert created.status == "committed"
    assert issued.nonce == "nonce-once"
    assert confirmed.status == "committed"
    assert all(
        request.actor_role is ActorRole.JUDGE_OPERATOR
        for request in actions.requests
    )
    assert all(request.actor_id == "operator:owner" for request in actions.requests)
    assert actions.requests[-1].receipt_content == receipt


def test_product_ticket_service_routes_connector_mode_through_configured_port() -> None:
    actions = _ProtectedTicketSpy()
    connector = _FakeConnector()
    service = ProductTicketService(
        actions,
        actor_id="operator:owner",
        clock=lambda: AT,
        connector=connector,
    )

    response = service.confirm_placement(
        "ticket-artifact-1",
        ConfirmPlacementCommand(
            confirmation_id="confirmation-1",
            nonce="nonce-once",
            ticket_hash="a" * 64,
            amount=100.0,
            currency="CNY",
            channel="jczq",
            placement_mode="connector",
            external_reference="browser-cannot-choose-this",
            idempotency_key="m4:confirm:connector",
        ),
    )

    assert response.status == "committed"
    assert len(connector.requests) == 1
    connector_request = connector.requests[0]
    assert connector_request.ticket_artifact_id == "ticket-artifact-1"
    assert connector_request.ticket_hash == "a" * 64
    assert not hasattr(connector_request, "nonce")
    persisted = actions.requests[-1]
    assert persisted.placement_mode == "connector"
    assert persisted.external_reference == "connector-order-001"
    assert persisted.receipt_content == b"fake connector receipt"
    assert persisted.receipt_content_type == "application/json"


def test_product_ticket_service_blocks_connector_mode_when_port_is_absent() -> None:
    actions = _ProtectedTicketSpy()
    service = ProductTicketService(actions, actor_id="operator:owner", clock=lambda: AT)

    with pytest.raises(ProductTicketError) as captured:
        service.confirm_placement(
            "ticket-artifact-1",
            ConfirmPlacementCommand(
                confirmation_id="confirmation-1",
                nonce="nonce-once",
                ticket_hash="a" * 64,
                amount=100.0,
                currency="CNY",
                channel="jczq",
                placement_mode="connector",
                external_reference="ignored",
                idempotency_key="m4:confirm:no-connector",
            ),
        )

    assert captured.value.code == "connector_unavailable"
    assert actions.requests == []
