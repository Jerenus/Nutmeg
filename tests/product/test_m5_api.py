from datetime import UTC, datetime

from fastapi.testclient import TestClient

from nutmeg.analytics.lifecycle import PROPOSAL_COLUMNS
from nutmeg.analytics.substrate import AnalyticsProjectionBuilder
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.workflow_actions import RecordAdjudicationRequest
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.decision import FactorDefinitionRow, FactorFamilyRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository
from nutmeg.product.wiring import ProductServices

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _services(seeded_product) -> ProductServices:
    repository = ProductReadRepository(
        seeded_product.kernel.engine,
        seeded_product.kernel.paths.analytics,
    )
    return ProductServices(
        kernel=seeded_product.kernel,
        queries=ProductQueryService(repository, seeded_product.kernel),
        actions=ProductActionGateway(
            seeded_product.kernel, repository, clock=lambda: AT
        ),
        settings=seeded_product.settings,
    )


def _client(seeded_product) -> TestClient:
    return TestClient(
        create_product_app(
            _services(seeded_product),
            session_secret="m5-api-session",
            csrf_secret="m5-api-csrf",
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


def test_m5_read_routes_publish_strict_degraded_contracts(seeded_product) -> None:
    client = _client(seeded_product)

    responses = {
        "review": client.get("/api/v1/review?as_of=2026-08-24T10:00:00Z"),
        "calibration": client.get(
            "/api/v1/calibration?as_of=2026-08-24T10:00:00Z"
        ),
        "ontology": client.get(
            "/api/v1/ontology/objects?type=team&q=FC&limit=1&as_of="
            "2026-08-24T10:00:00Z"
        ),
        "detail": client.get(
            "/api/v1/ontology/objects/match/match-1?as_of="
            "2026-08-24T10:00:00Z"
        ),
        "scoreboard": client.get(
            "/api/v1/scoreboard?as_of=2026-08-24T10:00:00Z"
        ),
    }

    assert all(response.status_code == 200 for response in responses.values())
    assert responses["review"].json()["forecast"]["health"]["code"] == (
        "projection_unavailable"
    )
    assert responses["ontology"].json()["next_cursor"] is not None
    assert responses["detail"].json()["properties"]["current_revision_id"] == (
        "mr-before"
    )
    assert responses["scoreboard"].json()["authority"]["state"] == "legacy"
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/api/v1/review",
        "/api/v1/calibration",
        "/api/v1/ontology/objects",
        "/api/v1/ontology/objects/{object_type}/{object_id}",
        "/api/v1/scoreboard",
    } <= paths.keys()
    assert not any(
        word in path for path in paths for word in ("shadow", "cutover", "export")
    )


def test_m5_read_validation_and_not_found_use_stable_errors(seeded_product) -> None:
    client = _client(seeded_product)

    naive = client.get("/api/v1/review?as_of=2026-08-24T10:00:00")
    disallowed = client.get(
        "/api/v1/ontology/objects?type=source_artifacts&limit=10"
    )
    missing = client.get("/api/v1/ontology/objects/match/absent")
    invalid_limit = client.get("/api/v1/ontology/objects?type=team&limit=0")

    assert naive.status_code == 422
    assert naive.json()["code"] == "validation_error"
    assert disallowed.status_code == 422
    assert disallowed.json()["code"] == "validation_error"
    assert missing.status_code == 404
    assert missing.json()["code"] == "object_not_found"
    assert invalid_limit.status_code == 422


def test_manual_observation_action_uses_server_actor_and_requires_evidence(
    seeded_product,
) -> None:
    client = _client(seeded_product)
    headers = _session(client)
    body = {
        "action_type": "record_scoreboard_observation",
        "idempotency_key": "m5:api:observation",
        "payload": {
            "group_key": "manual",
            "metric_key": "reviewed",
            "tally": "1/1",
            "detail": "operator reviewed the settled sample",
            "status": "active",
            "numerator": 1,
            "denominator": 1,
            "value": 1,
            "unit": "ratio",
            "evidence_refs": [
                {"object_type": "adjudication", "object_id": "adjudication-fixture"}
            ],
            "effective_at": "2026-08-24T10:00:00Z",
            "supersedes_observation_id": None,
        },
        "expected_versions": {},
    }

    committed = client.post("/api/v1/actions", json=body, headers=headers)
    missing_evidence = client.post(
        "/api/v1/actions",
        json={
            **body,
            "idempotency_key": "m5:api:observation:no-evidence",
            "payload": {**body["payload"], "evidence_refs": []},
        },
        headers=headers,
    )

    assert committed.status_code == 200
    assert committed.json()["status"] == "committed"
    assert missing_evidence.status_code == 422
    with OntologyUnitOfWork(seeded_product.kernel.engine) as uow:
        observation = uow.scoreboard.latest_observations(as_of=AT.isoformat())[0]
        actor = uow.connection.execute(
            schema.actions.select().where(
                schema.actions.c.action_id == committed.json()["action_id"]
            )
        ).mappings().one()
    assert observation.group_key == "manual"
    assert actor["actor_id"] == seeded_product.settings.default_user_id
    assert actor["actor_role"] == "judge_operator"


def test_factor_lifecycle_action_is_bound_to_current_proposal_and_adjudication(
    seeded_product,
) -> None:
    kernel = seeded_product.kernel
    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.decision.insert_factor_family(
            FactorFamilyRow("family-rest", "rest", None)
        )
        uow.decision.insert_factor_definition(
            FactorDefinitionRow(
                factor_definition_id="factor-rest",
                factor_family_id="family-rest",
                version=1,
                name="rest edge",
                definition=None,
                scope=None,
                status="probation",
                born_from_refs=[],
                valid_from=AT.isoformat(),
                valid_to=None,
                policy_version="governance-v1",
            )
        )
    adjudication = kernel.workflow.record_adjudication(
        RecordAdjudicationRequest(
            subject_type="factor_definition",
            subject_id="factor-rest",
            decision="apply",
            reason="sample and interval satisfy the registered lifecycle policy",
            evidence_rejected=[],
            alternative={},
            supersedes_adjudication_id=None,
            actor_id="operator:owner",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m5:factor:adjudication",
            requested_at=AT,
        )
    )
    adjudication_id = adjudication.result_refs[0].object_id

    def proposal(context) -> None:
        context.write(
            "factor_lifecycle_proposals",
            [
                {
                    "proposal_id": "factor-rest:probation->active",
                    "factor_definition_id": "factor-rest",
                    "from_status": "probation",
                    "to_status": "active",
                    "rationale_json": '{"n_eff":12}',
                    "policy_version": "lifecycle-v1",
                }
            ],
            column_types=PROPOSAL_COLUMNS,
        )

    AnalyticsProjectionBuilder(
        kernel.engine, kernel.paths.analytics
    ).build(
        [("factor_lifecycle_proposals", "lc-v1", proposal)],
        built_at="2026-08-24T10:05:00+00:00",
    )
    client = _client(seeded_product)
    body = {
        "action_type": "apply_factor_status",
        "idempotency_key": "m5:api:factor:apply",
        "payload": {
            "proposal_id": "factor-rest:probation->active",
            "factor_definition_id": "factor-rest",
            "expected_current_status": "probation",
            "target_status": "active",
            "adjudication_id": adjudication_id,
        },
        "expected_versions": {"factor_definition:factor-rest": 1},
    }

    applied = client.post("/api/v1/actions", json=body, headers=_session(client))
    stale = client.post(
        "/api/v1/actions",
        json={**body, "idempotency_key": "m5:api:factor:stale"},
        headers=_session(client),
    )
    spoofed = client.post(
        "/api/v1/actions",
        json={**body, "actor_role": "ai_analyst"},
        headers=_session(client),
    )

    assert applied.status_code == 200
    assert applied.json()["status"] == "committed"
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"
    assert spoofed.status_code == 422
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.decision.factor_status("factor-rest") == "active"


def test_browser_cannot_invoke_scoreboard_authority_actions(seeded_product) -> None:
    client = _client(seeded_product)
    response = client.post(
        "/api/v1/actions",
        json={
            "action_type": "approve_scoreboard_cutover",
            "idempotency_key": "m5:api:forbidden-cutover",
            "payload": {},
            "expected_versions": {},
        },
        headers=_session(client),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "action_not_allowed"
