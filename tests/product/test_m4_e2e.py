import base64
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_finance as sf
from nutmeg.ontology.repository import schema_tickets as st
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.market import QuoteRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.contracts import (
    ApproveTicketBatchCommand,
    ConfirmPlacementCommand,
    CreateTicketBatchCommand,
    IssueConfirmationCommand,
    ProductActionRequest,
    RemoveTicketLegCommand,
)
from nutmeg.product.errors import ProductTicketError
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from nutmeg.product.tickets import ProductTicketService

AT = datetime(2026, 8, 24, 10, 30, tzinfo=UTC)
RECEIPT = b"manual placement receipt fixture"


def _services(settings, kernel=None):
    current_kernel = kernel or build_ontology_kernel(settings)
    repository = ProductReadRepository(current_kernel.engine)
    return SimpleNamespace(
        kernel=current_kernel,
        queries=ProductQueryService(repository, current_kernel),
        actions=ProductActionGateway(
            current_kernel,
            repository,
            clock=lambda: AT,
        ),
        settings=settings,
        copilot=None,
        tickets=ProductTicketService(
            current_kernel.protected_tickets,
            actor_id=settings.default_user_id,
            clock=lambda: AT,
        ),
    )


def _client(services) -> TestClient:
    return TestClient(
        create_product_app(
            services,
            session_secret="m4-e2e-session-secret",
            csrf_secret="m4-e2e-csrf-secret",
            clock=lambda: AT,
        )
    )


def _session(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    assert response.status_code == 200
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def _ref(response, object_type: str) -> str:
    payload = (
        response.model_dump(mode="json")
        if hasattr(response, "model_dump")
        else response.json()
    )
    return next(
        item["object_id"]
        for item in payload["result_refs"]
        if item["object_type"] == object_type
    )


def _batch_for_revision(client: TestClient, revision_id: str) -> dict[str, object]:
    response = client.get(
        "/api/v1/ticket-workbench"
        "?date=2026-08-24&as_of=2026-08-24T10:30:00Z"
    )
    assert response.status_code == 200
    return next(
        item
        for item in response.json()["batch_revisions"]
        if item["ticket_batch_revision_id"] == revision_id
    )


def _leg(match: dict[str, object], *, mode: str) -> dict[str, object]:
    selection = next(
        item for item in match["selections"] if item["outcome_key"] == "home"
    )
    return {
        "leg_key": "match-1:md-had:home",
        "match_id": match["match_id"],
        "match_no": match["match_no"],
        "name": f'{match["home_team"]} - {match["away_team"]}',
        "market_definition_id": match["market_definition_id"],
        "selection_id": selection["selection_id"],
        "outcome_key": selection["outcome_key"],
        "faces": "31" if mode == "warn" else "3",
        "forecast_revision_id": match["forecast_revision_id"],
        "entry_quote_id": selection["quote_id"],
        "odds": selection["odds"],
        "line": selection["line"],
        "bucket": "main",
        "fair": match["belief_distribution"],
        "confidence": 3 if mode == "error" else 4,
        "directional_flags": [],
        "nondirectional_flags": (
            ["two_way_instability"] if mode == "warn" else []
        ),
        "anchor_integrity": "pass",
        "precedents": [],
    }


def _create_payload(match: dict[str, object], *, mode: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "run_date": "2026-08-24",
        "channel": "jczq",
        "account_id": "acct-jczq",
        "currency": "CNY",
        "deadline_at": "2026-08-24T11:30:00Z",
        "legs": [_leg(match, mode=mode)],
        "idempotency_key": f"m4:e2e:create:{mode}",
    }


def _counts(kernel) -> dict[str, int]:
    with OntologyUnitOfWork(kernel.engine) as uow:
        connection = uow.connection
        return {
            "actions": connection.execute(
                select(func.count()).select_from(schema.actions)
            ).scalar_one(),
            "events": connection.execute(
                select(func.count()).select_from(sw.outbox_events)
            ).scalar_one(),
            "source_artifacts": connection.execute(
                select(func.count()).select_from(schema.source_artifacts)
            ).scalar_one(),
            "retrievals": connection.execute(
                select(func.count()).select_from(schema.artifact_retrievals)
            ).scalar_one(),
            "batches": connection.execute(
                select(func.count(func.distinct(st.ticket_batch_revisions.c.ticket_batch_id)))
            ).scalar_one(),
            "revisions": connection.execute(
                select(func.count()).select_from(st.ticket_batch_revisions)
            ).scalar_one(),
            "ticket_artifacts": connection.execute(
                select(func.count()).select_from(st.audited_ticket_artifacts)
            ).scalar_one(),
            "confirmations": connection.execute(
                select(func.count()).select_from(st.ticket_confirmation_challenges)
            ).scalar_one(),
            "placements": connection.execute(
                select(func.count()).select_from(st.ticket_placements)
            ).scalar_one(),
            "tickets": connection.execute(
                select(func.count()).select_from(sf.tickets)
            ).scalar_one(),
            "bet_legs": connection.execute(
                select(func.count()).select_from(sf.bet_legs)
            ).scalar_one(),
            "cash_transactions": connection.execute(
                select(func.count()).select_from(sf.cash_transactions)
            ).scalar_one(),
        }


def _cas_bytes(kernel, artifact_id: str) -> bytes:
    digest = artifact_id.removeprefix("sha256:")
    return (kernel.paths.artifacts / "sha256" / digest[:2] / digest).read_bytes()


def test_m4_golden_path_is_audited_restart_safe_and_exactly_once(
    m3_seeded_product,
) -> None:
    kernel = m3_seeded_product.kernel
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
        uow.market.insert_quote(
            QuoteRow(
                quote_id="quote-m4-home",
                match_id="match-1",
                market_definition_id="md-had",
                selection_id="sel-had-home",
                provider="sporttery",
                bookmaker=None,
                decimal_odds=2.1,
                captured_at="2026-08-24T10:20:00+00:00",
                artifact_retrieval_id=None,
                quote_status="active",
            )
        )
    baseline = _counts(kernel)
    services = _services(m3_seeded_product.settings, kernel)
    client = _client(services)
    headers = _session(client)

    page = client.get("/tickets?date=2026-08-24")
    workbench = client.get(
        "/api/v1/ticket-workbench"
        "?date=2026-08-24&as_of=2026-08-24T10:30:00Z"
    )
    assert page.status_code == 200
    assert workbench.status_code == 200
    match = next(
        item for item in workbench.json()["matches"] if item["match_id"] == "match-1"
    )
    assert match["eligible"] is True

    spoofed = client.post(
        "/api/v1/ticket-batches",
        headers=headers,
        json={
            **_create_payload(match, mode="error"),
            "idempotency_key": "m4:e2e:spoofed",
            "actor_role": "ai_analyst",
        },
    )
    assert spoofed.status_code == 405

    error_created = services.tickets.create_batch(
        CreateTicketBatchCommand.model_validate(_create_payload(match, mode="error"))
    )
    assert error_created.status == "committed"
    error_revision_id = _ref(error_created, "ticket_batch_revision")
    error_batch = _batch_for_revision(client, error_revision_id)
    assert error_batch["audit_state"] == "error"
    with pytest.raises(ProductTicketError, match="audit ERROR") as error_approval:
        services.tickets.approve_batch(
            str(error_batch["ticket_batch_id"]),
            ApproveTicketBatchCommand(
                expected_revision_no=1,
                idempotency_key="m4:e2e:approve:error",
            ),
        )
    assert error_approval.value.code == "ticket_audit_blocked"
    assert _counts(kernel)["ticket_artifacts"] == baseline["ticket_artifacts"]

    warn_created = services.tickets.create_batch(
        CreateTicketBatchCommand.model_validate(_create_payload(match, mode="warn"))
    )
    assert warn_created.status == "committed"
    warn_revision_id = _ref(warn_created, "ticket_batch_revision")
    warn_batch = _batch_for_revision(client, warn_revision_id)
    warning = next(
        item for item in warn_batch["audit_findings"] if item["level"] == "WARN"
    )
    with pytest.raises(ProductTicketError, match="unadjudicated WARN") as warn_blocked:
        services.tickets.approve_batch(
            str(warn_batch["ticket_batch_id"]),
            ApproveTicketBatchCommand(
                expected_revision_no=1,
                idempotency_key="m4:e2e:approve:warn:blocked",
            ),
        )
    assert warn_blocked.value.code == "ticket_warning_unadjudicated"

    adjudicated = services.actions.execute(
        ProductActionRequest.model_validate(
            {
            "schema_version": "1",
            "action_type": "record_adjudication",
            "idempotency_key": "m4:e2e:warn:adjudication",
            "payload": {
                "subject_type": "ticket_audit_finding",
                "subject_id": warning["finding_id"],
                "decision": "accept_warning",
                "reason": "The residual risk is explicit after source review.",
                "evidence_rejected": [
                    {"object_type": "claim", "object_id": "claim-conflict"}
                ],
                "alternative": {"action": "drop_match"},
            },
            "expected_versions": {},
            }
        )
    )
    assert adjudicated.status == "committed"
    warn_approved = services.tickets.approve_batch(
        str(warn_batch["ticket_batch_id"]),
        ApproveTicketBatchCommand(
            expected_revision_no=1,
            idempotency_key="m4:e2e:approve:warn",
        ),
    )
    assert warn_approved.status == "committed"
    artifact_id = _ref(warn_approved, "audited_ticket_artifact")
    artifact = client.get(f"/api/v1/ticket-artifacts/{artifact_id}").json()
    assert artifact["placement_state"] == "unplaced"
    assert artifact["confirmation_state"] == "not_issued"
    assert _counts(kernel)["cash_transactions"] == baseline["cash_transactions"]
    artifact_bytes = _cas_bytes(kernel, artifact["source_artifact_id"])
    assert hashlib.sha256(artifact_bytes).hexdigest() == artifact["ticket_hash"]
    assert json.loads(artifact_bytes) == artifact["payload"]

    issued = services.tickets.issue_confirmation(
        artifact_id,
        IssueConfirmationCommand(idempotency_key="m4:e2e:confirmation"),
    )
    assert issued.status == "committed"
    nonce = issued.nonce
    confirmation_id = issued.confirmation_id
    assert nonce and confirmation_id
    cursor = client.get("/api/v1/events?after=0&limit=1000").json()["next_cursor"]

    restarted_services = _services(m3_seeded_product.settings)
    restarted = _client(restarted_services)
    confirm_payload = {
        "schema_version": "1",
        "confirmation_id": confirmation_id,
        "nonce": nonce,
        "ticket_hash": artifact["ticket_hash"],
        "amount": artifact["amount"],
        "currency": artifact["currency"],
        "channel": artifact["channel"],
        "placement_mode": "manual",
        "external_reference": "manual-e2e-001",
        "receipt_base64": base64.b64encode(RECEIPT).decode("ascii"),
        "receipt_content_type": "text/plain",
        "idempotency_key": "m4:e2e:confirm",
    }
    confirmed = restarted_services.tickets.confirm_placement(
        artifact_id,
        ConfirmPlacementCommand.model_validate(confirm_payload),
    )
    assert confirmed.status == "committed"
    ticket_id = _ref(confirmed, "ticket")
    cash_transaction_id = _ref(confirmed, "cash_transaction")
    placement_id = _ref(confirmed, "ticket_placement")
    receipt_artifact_id = _ref(confirmed, "source_artifact")

    replayed = restarted_services.tickets.confirm_placement(
        artifact_id,
        ConfirmPlacementCommand.model_validate(confirm_payload),
    )
    assert replayed.action_id == confirmed.action_id
    with pytest.raises(ProductTicketError) as reused:
        restarted_services.tickets.confirm_placement(
            artifact_id,
            ConfirmPlacementCommand.model_validate(
                {**confirm_payload, "idempotency_key": "m4:e2e:confirm:reused"}
            ),
        )
    assert reused.value.code in {"confirmation_reused", "ticket_already_placed"}

    placed = restarted.get(f"/api/v1/ticket-artifacts/{artifact_id}").json()
    assert placed["placement_state"] == "placed"
    assert placed["ticket_id"] == ticket_id
    assert placed["ticket_placement_id"] == placement_id
    assert placed["receipt_artifact_id"] == receipt_artifact_id
    assert _cas_bytes(kernel, receipt_artifact_id) == RECEIPT

    lineage = restarted.get(
        f"/api/v1/lineage/audited_ticket_artifact/{artifact_id}"
    )
    assert lineage.status_code == 200
    assert {edge["relation"] for edge in lineage.json()["edges"]} >= {
        "ticket_artifact_for_batch_revision",
        "ticket_artifact_stored_as_source",
        "ticket_artifact_has_placement",
        "ticket_artifact_placed_as_ticket",
    }
    ticket_lineage = restarted.get(f"/api/v1/lineage/ticket/{ticket_id}").json()
    assert any(
        edge["relation"] == "ticket_uses_forecast"
        and edge["target"]["object_id"] == match["forecast_revision_id"]
        for edge in ticket_lineage["edges"]
    )

    event_stream = restarted.get(
        f"/api/v1/events/stream?after={cursor}&once=true"
    )
    assert event_stream.status_code == 200
    assert f'id: {cursor + 1}' in event_stream.text
    assert "event: action.committed" in event_stream.text

    empty_created = restarted_services.tickets.create_batch(
        CreateTicketBatchCommand.model_validate(_create_payload(match, mode="clean"))
    )
    assert empty_created.status == "committed"
    empty_first = _batch_for_revision(
        restarted, _ref(empty_created, "ticket_batch_revision")
    )
    emptied = restarted_services.tickets.remove_leg(
        str(empty_first["ticket_batch_id"]),
        RemoveTicketLegCommand(
            leg_key="match-1:md-had:home",
            expected_revision_no=1,
            idempotency_key="m4:e2e:empty:remove",
        ),
    )
    assert emptied.status == "committed"
    approved_empty = restarted_services.tickets.approve_batch(
        str(empty_first["ticket_batch_id"]),
        ApproveTicketBatchCommand(
            expected_revision_no=2,
            idempotency_key="m4:e2e:empty:approve",
        ),
    )
    assert approved_empty.status == "committed"
    assert not any(
        item.object_type == "audited_ticket_artifact"
        for item in approved_empty.result_refs
    )
    empty_current = _batch_for_revision(
        restarted, _ref(approved_empty, "ticket_batch_revision")
    )
    assert empty_current["state"] == "approved_empty"

    final = _counts(kernel)
    assert {key: final[key] - baseline[key] for key in final} == {
        "actions": 12,
        "events": 12,
        "source_artifacts": 8,
        "retrievals": 1,
        "batches": 3,
        "revisions": 6,
        "ticket_artifacts": 1,
        "confirmations": 1,
        "placements": 1,
        "tickets": 1,
        "bet_legs": 1,
        "cash_transactions": 1,
    }
    with OntologyUnitOfWork(kernel.engine) as uow:
        [debit] = uow.connection.execute(
            select(sf.cash_transactions).where(
                sf.cash_transactions.c.transaction_id == cash_transaction_id
            )
        ).mappings().all()
        [challenge] = uow.connection.execute(
            select(st.ticket_confirmation_challenges).where(
                st.ticket_confirmation_challenges.c.confirmation_id == confirmation_id
            )
        ).mappings().all()
        assert debit["ticket_id"] == ticket_id
        assert debit["kind"] == "stake"
        assert debit["amount"] == -artifact["amount"]
        assert uow.finance.ledger_balance("acct-jczq") == -artifact["amount"]
        assert challenge["nonce_hash"] == hashlib.sha256(nonce.encode()).hexdigest()
        assert challenge["consumed_at"] is not None

    actions = restarted.get("/api/v1/actions?limit=1000").text
    events = restarted.get("/api/v1/events?after=0&limit=1000").text
    for feed in (actions, events):
        assert nonce not in feed
        assert confirm_payload["receipt_base64"] not in feed
