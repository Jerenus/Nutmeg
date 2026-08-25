from datetime import timedelta

from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.models import ActorRole, ObjectRef
from nutmeg.ontology.actions.reliability_actions import (
    RecordReliabilityEvidenceRequest,
)
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from nutmeg.product.wiring import ProductServices
from tests.reliability.test_release_policy import (
    COMMIT,
    NOW,
    _record_system,
    _seed_soak,
    _seed_system,
)


def _record_release_detail(
    kernel,
    *,
    kind: str,
    report: dict[str, object],
) -> None:
    kernel.reliability_actions.record_evidence(
        RecordReliabilityEvidenceRequest(
            evidence_kind=kind,
            workflow="system",
            business_date=None,
            observed_from=NOW - timedelta(minutes=10),
            observed_to=NOW - timedelta(minutes=2),
            status="passed",
            report=report,
            source_refs=[ObjectRef("test_run", f"detailed-{kind}")],
            actor_id="system:m6-product-test",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=f"m6:product-detail:{kind}",
            requested_at=NOW - timedelta(minutes=1),
        )
    )


def _seed_release_details(kernel) -> None:
    _record_release_detail(
        kernel,
        kind="scheduler_authority",
        report={
            "candidate_commit": COMMIT,
            "policy_version": "release-v1",
            "checks": {"authority": True},
            "summary": {
                "ontology_v2": True,
                "scoreboard_authority": "ontology",
                "sop_ready": True,
                "stages": [
                    {"stage": "am", "configured": True, "loaded": True},
                    {"stage": "close", "configured": True, "loaded": True},
                    {"stage": "settle", "configured": True, "loaded": True},
                ],
                "secret": "must-not-leak",
            },
        },
    )
    _record_release_detail(
        kernel,
        kind="backup_restore",
        report={
            "candidate_commit": COMMIT,
            "policy_version": "release-v1",
            "checks": {"restore": True},
            "summary": {
                "sqlite_integrity": "ok",
                "schema_version": 14,
                "action_high_watermark": 27,
                "outbox_cursor": 27,
                "projection_high_watermark": 27,
                "source_manifest_sha256": "d" * 64,
                "source_data_root": "/must/not/leak",
            },
        },
    )


def _services(seeded_product) -> ProductServices:
    repository = ProductReadRepository(
        seeded_product.kernel.engine,
        seeded_product.kernel.paths.analytics,
    )
    return ProductServices(
        kernel=seeded_product.kernel,
        queries=ProductQueryService(repository, seeded_product.kernel),
        actions=ProductActionGateway(
            seeded_product.kernel, repository, clock=lambda: NOW
        ),
        settings=seeded_product.settings,
    )


def _client(seeded_product) -> TestClient:
    return TestClient(
        create_product_app(
            _services(seeded_product),
            session_secret="m6-api-session",
            csrf_secret="m6-api-csrf",
            clock=lambda: NOW,
        )
    )


def _session(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def _release_url() -> str:
    return (
        "/api/v1/release?release_version=v1.0.0&candidate_commit="
        f"{COMMIT}&evaluated_at=2026-08-24T12:00:00Z"
    )


def test_release_and_metrics_routes_publish_strict_empty_state(seeded_product) -> None:
    client = _client(seeded_product)

    release = client.get(_release_url())
    metrics = client.get("/api/v1/reliability/metrics?as_of=2026-08-24T12:00:00Z")

    assert release.status_code == 200
    payload = release.json()
    assert payload["ready"] is False
    assert [gate["gate_id"] for gate in payload["gates"]] == [
        "G1",
        "G2",
        "G3",
        "G4",
        "G5",
        "G6",
    ]
    assert payload["approval_status"] == "none"
    assert payload["scheduler_authority"] is None
    assert payload["backup_restore"] is None
    assert payload["performance"] == []
    assert metrics.status_code == 200
    assert metrics.json()["authority_state"] == "legacy"
    assert "report" not in release.text
    assert "source_refs" not in release.text
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/release" in paths
    assert "/api/v1/reliability/metrics" in paths


def test_release_route_reaches_green_fixture_without_client_arithmetic(
    seeded_product,
) -> None:
    _seed_system(seeded_product.kernel)
    _seed_soak(seeded_product.kernel)
    _seed_release_details(seeded_product.kernel)

    response = _client(seeded_product).get(_release_url())

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert all(gate["passed"] for gate in payload["gates"])
    assert {item["workflow"] for item in payload["soak_coverage"]} == {
        "jczq",
        "zucai",
    }
    assert all(item["distinct_days"] == 14 for item in payload["soak_coverage"])
    assert payload["scheduler_authority"] == {
        "reliability_evidence_id": payload["scheduler_authority"][
            "reliability_evidence_id"
        ],
        "status": "passed",
        "observed_to": "2026-08-24T11:58:00Z",
        "ontology_v2": True,
        "scoreboard_authority": "ontology",
        "sop_ready": True,
        "configured_stages": 3,
        "loaded_stages": 3,
    }
    assert payload["backup_restore"]["sqlite_integrity"] == "ok"
    assert payload["backup_restore"]["schema_version"] == 14
    assert payload["backup_restore"]["action_high_watermark"] == 27
    assert payload["backup_restore"]["source_manifest_sha256"] == "d" * 64
    assert {row["metric"] for row in payload["performance"]} == {
        "board_query_ms",
        "match_query_ms",
        "action_ack_ms",
        "event_reconnect_ms",
    }
    assert all(row["sample_count"] == 20 for row in payload["performance"])
    assert "must-not-leak" not in response.text
    assert "/must/not/leak" not in response.text


def test_release_routes_require_aware_time_and_nonblank_candidate(
    seeded_product,
) -> None:
    client = _client(seeded_product)

    naive = client.get(
        "/api/v1/release?release_version=v1&candidate_commit=abc&"
        "evaluated_at=2026-08-24T12:00:00"
    )
    blank = client.get(
        "/api/v1/release?release_version=v1&candidate_commit=&"
        "evaluated_at=2026-08-24T12:00:00Z"
    )

    assert naive.status_code == 422
    assert naive.json()["code"] == "validation_error"
    assert blank.status_code == 422


def test_generic_approval_uses_server_judge_and_rejects_stale_snapshot(
    seeded_product,
) -> None:
    kernel = seeded_product.kernel
    _seed_system(kernel)
    _seed_soak(kernel)
    client = _client(seeded_product)
    headers = _session(client)
    first = client.get(_release_url()).json()
    body = {
        "action_type": "approve_release",
        "idempotency_key": "m6:api:approve",
        "payload": {
            "release_version": "v1.0.0",
            "candidate_commit": COMMIT,
            "expected_snapshot_sha256": first["evidence_snapshot_sha256"],
            "reason": "reviewed exact server-side release evidence",
        },
        "expected_versions": {},
    }

    spoofed = client.post(
        "/api/v1/actions",
        json={
            **body,
            "idempotency_key": "m6:api:approve:spoofed",
            "payload": {**body["payload"], "actor_role": "ai_analyst"},
        },
        headers=headers,
    )
    assert spoofed.status_code == 422

    _record_system(kernel, "observability", suffix="api-new-current")
    stale = client.post("/api/v1/actions", json=body, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"

    current = client.get(_release_url()).json()
    body["idempotency_key"] = "m6:api:approve:current"
    body["payload"]["expected_snapshot_sha256"] = current[
        "evidence_snapshot_sha256"
    ]
    approved = client.post("/api/v1/actions", json=body, headers=headers)

    assert approved.status_code == 200
    assert approved.json()["status"] == "committed"
    with OntologyUnitOfWork(kernel.engine) as uow:
        action = uow.connection.execute(
            schema.actions.select().where(
                schema.actions.c.action_id == approved.json()["action_id"]
            )
        ).mappings().one()
    assert action["actor_id"] == seeded_product.settings.default_user_id
    assert action["actor_role"] == "judge_operator"
