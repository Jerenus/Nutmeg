import base64
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.finance.reconcile_flow import ReconcileRequest
from nutmeg.ontology.repository.finance import CashAccountRow
from nutmeg.ontology.repository.market import QuoteRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from nutmeg.product.tickets import ProductTicketService
from tests.product.test_m4_e2e import (
    RECEIPT,
    _batch_for_revision,
    _create_payload,
    _ref,
    _session,
)
from tests.reliability.test_release_policy import (
    COMMIT,
    NOW,
    _seed_soak,
    _seed_system,
)

TICKET_AT = datetime(2026, 8, 24, 10, 30, tzinfo=UTC)


def _client_at(seeded_product, current_time: datetime) -> TestClient:
    kernel = seeded_product.kernel
    repository = ProductReadRepository(kernel.engine, kernel.paths.analytics)
    services = type(
        "M6Services",
        (),
        {
            "kernel": kernel,
            "queries": ProductQueryService(repository, kernel),
            "actions": ProductActionGateway(
                kernel, repository, clock=lambda: current_time
            ),
            "settings": seeded_product.settings,
            "copilot": None,
            "tickets": ProductTicketService(
                kernel.protected_tickets,
                actor_id=seeded_product.settings.default_user_id,
                clock=lambda: current_time,
            ),
        },
    )()
    return TestClient(
        create_product_app(
            services,
            session_secret="m6-e2e-session",
            csrf_secret="m6-e2e-csrf",
            clock=lambda: current_time,
        )
    )


def _release_url() -> str:
    return (
        "/api/v1/release?release_version=v1.0.0&candidate_commit="
        f"{COMMIT}&evaluated_at=2026-08-24T12:00:00Z"
    )


def test_m6_full_product_lifecycle_recovery_and_release_governance(
    m3_seeded_product,
) -> None:
    kernel = m3_seeded_product.kernel
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.finance.ensure_account(
            CashAccountRow("acct-jczq", "jczq", "CNY", "active")
        )
        uow.market.insert_quote(
            QuoteRow(
                quote_id="quote-m6-home",
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

    client = _client_at(m3_seeded_product, TICKET_AT)
    headers = _session(client)
    assert client.get("/operations").status_code == 200
    assert client.get("/matches/match-1").status_code == 200

    retracted = client.post(
        "/api/v1/actions",
        headers=headers,
        json={
            "action_type": "retract_claim",
            "idempotency_key": "m6:e2e:retract-conflict",
            "payload": {"claim_id": "claim-conflict"},
            "expected_versions": {},
        },
    )
    assert retracted.status_code == 200
    forecast = client.post(
        "/api/v1/actions",
        headers=headers,
        json={
            "action_type": "commit_forecast",
            "idempotency_key": "m6:e2e:forecast",
            "payload": {
                "match_id": "match-1",
                "market_definition_id": "md-had",
                "cutoff_at": "2026-08-24T10:30:00Z",
                "belief_distribution": {
                    "home": 0.56,
                    "draw": 0.27,
                    "away": 0.17,
                },
                "factors": [],
                "commitment_tier": "judged",
                "falsifier": "official lineup restores the unavailable starter",
            },
            "expected_versions": {"forecast:match-1:md-had": 1},
        },
    )
    assert forecast.status_code == 200

    workbench = client.get(
        "/api/v1/ticket-workbench?date=2026-08-24&"
        "as_of=2026-08-24T10:30:00Z"
    )
    match = next(
        item for item in workbench.json()["matches"] if item["match_id"] == "match-1"
    )
    created = client.post(
        "/api/v1/ticket-batches",
        headers=headers,
        json={
            **_create_payload(match, mode="clean"),
            "idempotency_key": "m6:e2e:create-ticket",
        },
    )
    assert created.status_code == 200
    revision_id = _ref(created, "ticket_batch_revision")
    batch = _batch_for_revision(client, revision_id)
    assert batch["audit_state"] == "clean"
    approved = client.post(
        f'/api/v1/ticket-batches/{batch["ticket_batch_id"]}/approve',
        headers=headers,
        json={
            "schema_version": "1",
            "expected_revision_no": 1,
            "idempotency_key": "m6:e2e:approve-ticket",
        },
    )
    assert approved.status_code == 200
    artifact_id = _ref(approved, "audited_ticket_artifact")
    artifact = client.get(f"/api/v1/ticket-artifacts/{artifact_id}").json()
    issued = client.post(
        f"/api/v1/ticket-artifacts/{artifact_id}/confirmations",
        headers=headers,
        json={
            "schema_version": "1",
            "idempotency_key": "m6:e2e:issue-confirmation",
        },
    )
    assert issued.status_code == 200
    confirmed = client.post(
        f"/api/v1/ticket-artifacts/{artifact_id}/confirm",
        headers=headers,
        json={
            "schema_version": "1",
            "confirmation_id": issued.json()["confirmation_id"],
            "nonce": issued.json()["nonce"],
            "ticket_hash": artifact["ticket_hash"],
            "amount": artifact["amount"],
            "currency": artifact["currency"],
            "channel": artifact["channel"],
            "placement_mode": "manual",
            "external_reference": "m6-local-e2e",
            "receipt_base64": base64.b64encode(RECEIPT).decode("ascii"),
            "receipt_content_type": "text/plain",
            "idempotency_key": "m6:e2e:confirm-ticket",
        },
    )
    assert confirmed.status_code == 200
    ticket_id = _ref(confirmed, "ticket")

    settled = kernel.reconcile.settle_match(
        ReconcileRequest(
            match_id="match-1",
            account_id="acct-jczq",
            score_90="2-0",
            status="final",
            source_artifact_retrieval_ids=[],
            actor_id="system:reconcile",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="m6:e2e:settle",
            requested_at=datetime(2026, 8, 24, 10, 45, tzinfo=UTC),
        )
    )
    assert settled.settled_ticket_ids == (ticket_id,)
    kernel.calibrate.build(
        CalibrateRequest(
            as_of="2026-08-24T11:00:00+00:00",
            built_at="2026-08-24T11:01:00+00:00",
        )
    )
    assert client.get("/review?as_of=2026-08-24T11:00:00Z").status_code == 200
    review = client.get("/api/v1/review?as_of=2026-08-24T11:00:00Z").json()
    assert any(item["ticket_id"] == ticket_id for item in review["settlements"])

    offline_path = kernel.paths.analytics.with_suffix(".offline")
    kernel.paths.analytics.replace(offline_path)
    offline = client.get("/api/v1/review?as_of=2026-08-24T11:00:00Z").json()
    assert offline["forecast"]["health"]["state"] == "unavailable"
    offline_path.replace(kernel.paths.analytics)
    restored = client.get("/api/v1/review?as_of=2026-08-24T11:00:00Z").json()
    assert restored["forecast"]["health"]["state"] in {"available", "stale"}

    cursor = client.get("/api/v1/events?after=0&limit=1000").json()["next_cursor"]
    client.post(
        "/api/v1/actions",
        headers=headers,
        json={
            "action_type": "record_adjudication",
            "idempotency_key": "m6:e2e:event-after-disconnect",
            "payload": {
                "subject_type": "event_stream",
                "subject_id": "reconnect",
                "decision": "hold",
                "reason": "prove durable cursor reconnect",
                "evidence_rejected": [],
                "alternative": {},
            },
            "expected_versions": {},
        },
    )
    resumed = client.get(
        f"/api/v1/events/stream?after={cursor}&once=true"
    )
    assert f"id: {cursor + 1}" in resumed.text

    release_client = _client_at(m3_seeded_product, NOW)
    release_headers = _session(release_client)
    blocked = release_client.get(_release_url()).json()
    assert blocked["ready"] is False
    blocked_approval = release_client.post(
        "/api/v1/actions",
        headers=release_headers,
        json={
            "action_type": "approve_release",
            "idempotency_key": "m6:e2e:blocked-approval",
            "payload": {
                "release_version": "v1.0.0",
                "candidate_commit": COMMIT,
                "expected_snapshot_sha256": blocked[
                    "evidence_snapshot_sha256"
                ],
                "reason": "this must remain blocked without evidence",
            },
            "expected_versions": {},
        },
    )
    assert blocked_approval.status_code == 422
    assert 'data-action="approve-release"' not in release_client.get(
        "/release?release_version=v1.0.0&candidate_commit=abc123&"
        "evaluated_at=2026-08-24T12:00:00Z"
    ).text

    _seed_system(kernel)
    _seed_soak(kernel)
    green = release_client.get(_release_url()).json()
    assert green["ready"] is True
    approved_release = release_client.post(
        "/api/v1/actions",
        headers=release_headers,
        json={
            "action_type": "approve_release",
            "idempotency_key": "m6:e2e:green-approval",
            "payload": {
                "release_version": "v1.0.0",
                "candidate_commit": COMMIT,
                "expected_snapshot_sha256": green[
                    "evidence_snapshot_sha256"
                ],
                "reason": "test-only fixture proves the guarded approval path",
            },
            "expected_versions": {},
        },
    )
    assert approved_release.status_code == 200
    current = release_client.get(_release_url()).json()
    assert current["approval_status"] == "current"
    assert 'data-approval-status="current"' in release_client.get(
        "/release?release_version=v1.0.0&candidate_commit=abc123&"
        "evaluated_at=2026-08-24T12:00:00Z"
    ).text
