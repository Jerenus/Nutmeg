from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings, OperatorRuntimeScope, OperatorSurfaceMode
from nutmeg.interfaces.cli import app as cli_app
from nutmeg.interfaces.cli import workflow as workflow_cli
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.models import ActionStatus
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import WorkflowActions
from nutmeg.ontology.operator.review_actions import OperatorReviewActions, ShadowReviewTokenCodec
from nutmeg.ontology.operator.sale_actions import (
    OfficialSaleSlateManifestV1,
    official_sale_parser_receipt_hash,
)
from nutmeg.ontology.repository import schema, schema_identity
from nutmeg.ontology.repository import schema_operator_decision as sod
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository import schema_operator_review as sorev
from nutmeg.ontology.repository import schema_operator_sale as sos
from nutmeg.ontology.repository import schema_tickets as st
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_runtime import OperatorRuntimeConfig
from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
from nutmeg.product.operator_workers import (
    OperatorInfrastructureWorkers,
    ScoreboardReviewCompletionWorker,
)
from nutmeg.product.wiring import build_product_services

FIXTURE_ROOT = Path("tests/product/fixtures/operator/current")
SIGNING_KEY = "package-twelve-isolated-replay-signing-key"


def _document(name: str) -> dict[str, object]:
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _external_scoreboard_update(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document["updated_at"] = "2026-09-05T10:00:00Z"
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _seed_sale_dependencies(data_dir: Path, manifests: tuple[OfficialSaleSlateManifestV1, ...]):
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir, _env_file=None))
    kernel.initialize()
    started_at = datetime(2026, 9, 5, 1, 55, tzinfo=UTC).isoformat()
    with kernel.engine.begin() as connection:
        for manifest in manifests:
            suffix = manifest.lane
            retrieval_id = manifest.official_source_artifact_retrieval_id
            artifact_id = f"artifact-current-{suffix}-sale"
            run_id = f"run-current-{suffix}-sale"
            receipt_hash = official_sale_parser_receipt_hash(
                lane=manifest.lane,
                business_key=manifest.business_key,
                published_at=manifest.published_at,
                offers=manifest.offers,
            )
            connection.execute(
                insert(schema.source_runs).values(
                    source_run_id=run_id,
                    source_name="sporttery",
                    source_type="official_schedule",
                    started_at=started_at,
                    finished_at=started_at,
                    status="succeeded",
                    error_code=None,
                    error_detail=None,
                )
            )
            connection.execute(
                insert(schema.source_artifacts).values(
                    artifact_id=artifact_id,
                    first_recorded_at=started_at,
                    content_type="application/json",
                    storage_path=f"sha256/current-{suffix}-sale",
                    byte_size=2,
                    content_hash=receipt_hash,
                )
            )
            connection.execute(
                insert(schema.artifact_retrievals).values(
                    artifact_retrieval_id=retrieval_id,
                    artifact_id=artifact_id,
                    source_run_id=run_id,
                    source_name="sporttery",
                    source_type="official_sale_schedule",
                    reported_content_type="application/json",
                    canonical_url=f"https://www.sporttery.cn/{suffix}/current.json",
                    requested_url=f"https://www.sporttery.cn/{suffix}/current.json",
                    published_at=manifest.published_at.isoformat(),
                    retrieved_at=manifest.retrieved_at.isoformat(),
                    status="stored",
                )
            )
            connection.execute(
                insert(schema_identity.matches),
                [
                    {"match_id": offer.canonical_match_id, "current_revision_id": None}
                    for offer in manifest.offers
                ],
            )
    return kernel


def _invoke_sale(data_dir: Path, name: str):
    return CliRunner().invoke(
        cli_app,
        [
            "workflow",
            "ingest-official-sale",
            "--manifest",
            str(FIXTURE_ROOT / name),
            "--contract-version",
            "official-sale-slate-v1",
            "--data-dir",
            str(data_dir),
        ],
    )


def _runtime(data_dir: Path, tmp_path: Path) -> OperatorRuntimeConfig:
    return OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=data_dir.resolve(),
        production_data_dir=(tmp_path / "production").resolve(),
        running_commit="package-twelve-isolated-replay",
    )


def _session_headers(client: TestClient) -> dict[str, str]:
    session = client.get("/api/v1/session")
    assert session.status_code == 200
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": session.json()["csrf_token"],
    }


def _review_services(
    *,
    fixture,
    data_dir: Path,
    tmp_path: Path,
    clock_at: datetime,
):
    from tests.product.operator_v2.test_review_ui import _ProjectionReadyRepository

    repository = _ProjectionReadyRepository(
        fixture.engine,
        data_dir / "ontology" / "analytics.duckdb",
    )
    action_service = ActionService(lambda: OntologyUnitOfWork(fixture.engine))
    snapshot_tokens = OperatorSnapshotTokenCodec(SIGNING_KEY)
    review_actions = OperatorReviewActions(
        action_service,
        shadow_token_signing_key=SIGNING_KEY,
    )
    queries = OperatorQueryService(
        repository=repository,
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: clock_at,
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=snapshot_tokens,
        shadow_review_tokens=ShadowReviewTokenCodec(SIGNING_KEY),
    )
    actions = OperatorActionService(
        queries=queries,
        action_gateway=SimpleNamespace(),
        workflow_actions=WorkflowActions(action_service),
        review_actions=review_actions,
        snapshot_tokens=snapshot_tokens,
        repository=repository,
        scoreboard_path=data_dir / "scoreboard.json",
        clock=lambda: clock_at,
    )
    workers = OperatorInfrastructureWorkers(
        data_dir=data_dir,
        clock=lambda: clock_at,
        poll_interval_seconds=0.01,
        scoreboard_review_completion=ScoreboardReviewCompletionWorker(
            action_service=action_service,
            review_actions=review_actions,
            scoreboard_path=data_dir / "scoreboard.json",
            worker_id="operator-scoreboard-review-completion",
            lease_duration=timedelta(minutes=5),
        ),
    )
    runtime = _runtime(data_dir, tmp_path)
    return SimpleNamespace(
        settings=SimpleNamespace(default_user_id="jun", data_dir=data_dir),
        runtime=runtime,
        queries=SimpleNamespace(),
        actions=SimpleNamespace(),
        operator_queries=queries,
        operator_actions=actions,
        copilot=None,
        tickets=SimpleNamespace(),
        infrastructure_workers=workers,
    ), runtime


def _business_counts(engine) -> tuple[int, ...]:
    tables = (
        sod.operator_evidence_freeze_requests,
        sod.operator_match_judgment_revisions,
        sod.operator_candidate_generation_requests,
        st.ticket_batch_revisions,
        st.ticket_placements,
        sor.operator_result_set_revisions,
        sor.operator_settlement_requests,
        sorev.operator_scoreboard_effect_disposition_revisions,
    )
    with engine.connect() as connection:
        return tuple(
            int(connection.scalar(select(func.count()).select_from(table)) or 0) for table in tables
        )


@pytest.mark.parametrize(
    ("name", "lane", "business_key", "offer_count"),
    (
        ("jczq-sale.json", "jczq", "2026-09-05", 2),
        ("zucai-issue.json", "zucai", "26117", 14),
    ),
)
def test_current_sale_fixtures_are_strict_public_contracts(
    name: str,
    lane: str,
    business_key: str,
    offer_count: int,
) -> None:
    manifest = OfficialSaleSlateManifestV1.model_validate(_document(name))

    assert manifest.lane == lane
    assert manifest.business_key == business_key
    assert len(manifest.offers) == offer_count


def test_scoreboard_fixture_changes_only_in_explicit_external_update_helper(
    tmp_path: Path,
) -> None:
    source = FIXTURE_ROOT / "scoreboard.json"
    scoreboard = tmp_path / "scoreboard.json"
    scoreboard.write_bytes(source.read_bytes())
    before = _sha256(scoreboard)

    assert _sha256(scoreboard) == before

    _external_scoreboard_update(scoreboard)

    assert _sha256(scoreboard) != before


def test_both_current_slates_enter_through_cli_and_render_from_v2_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    manifests = tuple(
        OfficialSaleSlateManifestV1.model_validate(_document(name))
        for name in ("jczq-sale.json", "zucai-issue.json")
    )
    kernel = _seed_sale_dependencies(data_dir, manifests)
    monkeypatch.setattr(
        workflow_cli,
        "_now",
        lambda: datetime(2026, 9, 5, 2, 2, tzinfo=UTC),
    )

    receipts = tuple(
        _invoke_sale(data_dir, name) for name in ("jczq-sale.json", "zucai-issue.json")
    )

    assert [receipt.exit_code for receipt in receipts] == [0, 0], [
        receipt.stdout for receipt in receipts
    ]
    assert [json.loads(receipt.stdout)["persisted_counts"] for receipt in receipts] == [
        {"offer_families": 2, "offer_revisions": 2, "slate_revisions": 1},
        {"offer_families": 14, "offer_revisions": 14, "slate_revisions": 1},
    ]
    with kernel.engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_sale_slate_revisions))
            == 2
        )
        assert (
            connection.scalar(select(func.count()).select_from(sos.official_offer_revisions)) == 16
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(schema.actions)
                .where(
                    schema.actions.c.action_type == "import_official_sale_slate",
                    schema.actions.c.status == ActionStatus.COMMITTED.value,
                )
            )
            == 2
        )

    scoreboard = data_dir / "scoreboard.json"
    scoreboard.write_bytes((FIXTURE_ROOT / "scoreboard.json").read_bytes())
    runtime = _runtime(data_dir, tmp_path)
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=runtime.production_data_dir,
        default_user_id="jun",
        operator_runtime_scope=runtime.runtime_scope,
        operator_surface_mode=runtime.surface_mode,
        operator_token_signing_key=SIGNING_KEY,
        operator_scheduler_enabled=False,
        telegram_bot_token=None,
    )
    services = build_product_services(settings, runtime_config=runtime)
    app = create_product_app(
        services,
        session_secret="package-twelve-session",
        csrf_secret="package-twelve-csrf",
        clock=lambda: datetime(2026, 9, 5, 9, tzinfo=UTC),
        runtime_config=runtime,
    )

    with TestClient(app) as client:
        today = client.get(
            "/api/v2/operator/today",
            params={"as_of": "2026-09-05T17:00:00+08:00"},
        )
        page = client.get(
            "/operator-next",
            params={"as_of": "2026-09-05T17:00:00+08:00"},
        )

    assert today.status_code == 200, today.text
    assert page.status_code == 200, page.text
    entries = today.json()["entries"]
    work_entries = [entry for entry in entries if entry["kind"] == "today_work_item_v1"]
    assert {(entry["lane"], entry["business_key"]) for entry in work_entries} == {
        ("jczq", "2026-09-05"),
        ("zucai", "26117"),
    }, today.json()
    assert {entry["phase"] for entry in work_entries} == {"prepare_evidence"}
    assert "竞彩 2026-09-05" in page.text
    assert "26117" in page.text


def test_public_judgment_candidate_and_approval_chain_uses_lifespan_worker(
    tmp_path: Path,
) -> None:
    from nutmeg.ontology.actions.protected_ticket_actions import ProtectedTicketActions
    from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
    from nutmeg.ontology.operator.result_actions import OperatorResultActions
    from nutmeg.ontology.repository.finance import CashAccountRow
    from nutmeg.product.actions import ProductActionGateway
    from nutmeg.product.operator_workers import CandidateGenerationWorker, audit_current_candidate
    from tests.ontology.operator.test_judgment_actions import (
        _baseline_request,
        _fixture,
    )
    from tests.product.operator_v2.test_judgment_api import (
        KEY,
        NOW,
        _envelope_document,
        _judgment_document,
        _seed_task_identity,
        _task_queries,
    )

    fixture = _fixture(tmp_path / "public-middle-chain")
    _seed_task_identity(fixture)
    fixture.decision_actions.freeze_market_prior_baseline(_baseline_request(fixture))
    with OntologyUnitOfWork(fixture.engine) as uow:
        uow.finance.ensure_account(CashAccountRow("acct-jczq", "jczq", "CNY", "active"))

    queries = _task_queries(fixture)
    result_actions = OperatorResultActions(fixture.action_service)
    protected = ProtectedTicketActions(
        fixture.action_service,
        ContentAddressedArtifactStore(tmp_path / "public-middle-chain-artifacts"),
        operator_decisions=fixture.decision_actions,
        operator_candidate_auditor=audit_current_candidate,
    )
    workflow_actions = WorkflowActions(fixture.action_service)
    action_gateway = ProductActionGateway(
        type("Kernel", (), {"workflow": workflow_actions})(),
        object(),
        clock=lambda: NOW,
    )
    actions = OperatorActionService(
        queries=queries,
        action_gateway=action_gateway,
        decision_actions=fixture.decision_actions,
        protected_tickets=protected,
        snapshot_tokens=OperatorSnapshotTokenCodec(KEY),
        clock=lambda: NOW,
    )
    data_dir = tmp_path / "public-middle-runtime"
    data_dir.mkdir(parents=True)
    scoreboard = data_dir / "scoreboard.json"
    scoreboard.write_bytes((FIXTURE_ROOT / "scoreboard.json").read_bytes())
    scoreboard_checksum = _sha256(scoreboard)
    workers = OperatorInfrastructureWorkers(
        data_dir=data_dir,
        clock=lambda: NOW,
        poll_interval_seconds=0.01,
        candidate_generation=CandidateGenerationWorker(
            action_service=fixture.action_service,
            result_actions=result_actions,
            worker_id="operator-e2e-candidate-generation",
            lease_duration=timedelta(minutes=5),
        ),
    )
    runtime = _runtime(data_dir, tmp_path)
    services = SimpleNamespace(
        settings=SimpleNamespace(default_user_id="jun", data_dir=data_dir),
        runtime=runtime,
        queries=SimpleNamespace(),
        actions=SimpleNamespace(),
        operator_queries=queries,
        operator_actions=actions,
        copilot=None,
        tickets=SimpleNamespace(),
        infrastructure_workers=workers,
    )
    app = create_product_app(
        services,
        session_secret="package-twelve-middle-session",
        csrf_secret="package-twelve-middle-csrf",
        clock=lambda: NOW,
        runtime_config=runtime,
    )

    with TestClient(app) as client:
        headers = _session_headers(client)
        envelope_task = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert envelope_task.status_code == 200, envelope_task.text
        envelope_step = envelope_task.json()["step"]
        assert envelope_step["mode"] == "baseline_envelope"
        envelope = client.post(
            "/api/v2/operator",
            headers=headers,
            json=_envelope_document(
                expected_snapshot_token=envelope_step["envelope_command_token"],
                idempotency_key="e2e:middle:envelope",
            ),
        )
        assert envelope.status_code == 200, envelope.text

        judgment_task = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert judgment_task.status_code == 200, judgment_task.text
        judgment_step = judgment_task.json()["step"]
        assert judgment_step["mode"] == "match_judgment"
        editor = judgment_step["editor"]
        judgment = client.post(
            "/api/v2/operator",
            headers=headers,
            json=_judgment_document(
                expected_snapshot_token=judgment_step["judgment_command_token"],
                idempotency_key="e2e:middle:judgment",
                belief=[
                    {"face_code": "3", "probability_decimal": "0.400000000000"},
                    {"face_code": "1", "probability_decimal": "0.300000000000"},
                    {"face_code": "0", "probability_decimal": "0.300000000000"},
                ],
                factors=[],
                evidence_ref_tokens=editor["evidence_ref_tokens"],
            ),
        )
        assert judgment.status_code == 200, judgment.text

        prescription_task = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert prescription_task.status_code == 200, prescription_task.text
        prescription_step = prescription_task.json()["step"]
        assert prescription_step["mode"] == "prescription_ready"
        prescription = client.post(
            "/api/v2/operator",
            headers=headers,
            json={
                "schema_version": "2",
                "kind": "freeze_judgment_prescription",
                "expected_snapshot_token": prescription_step["prescription_command_token"],
                "idempotency_key": "e2e:middle:prescription",
                "task_key": "jczq:2026-09-04",
                "judgment_revision_tokens": prescription_step["judgment_revision_tokens"],
            },
        )
        assert prescription.status_code == 200, prescription.text

        candidate_task = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert candidate_task.status_code == 200, candidate_task.text
        candidate_step = candidate_task.json()["step"]
        assert candidate_step["mode"] == "candidate_request"
        requested = client.post(
            "/api/v2/operator",
            headers=headers,
            json={
                "schema_version": "2",
                "kind": "request_candidate_generation",
                "expected_snapshot_token": candidate_step["request_generation_token"],
                "idempotency_key": "e2e:middle:candidate-request",
                "task_key": "jczq:2026-09-04",
                "market_prior_baseline_token": candidate_step["market_prior_baseline_token"],
                "baseline_envelope_token": candidate_step["baseline_envelope_token"],
                "judgment_prescription_token": candidate_step[
                    "judgment_prescription_token"
                ],
            },
        )
        assert requested.status_code == 202, requested.text

        for _attempt in range(100):
            comparison = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
            assert comparison.status_code == 200, comparison.text
            comparison_step = comparison.json()["step"]
            if comparison_step.get("mode") == "candidate_comparison":
                break
            time.sleep(0.02)
        else:
            pytest.fail("lifespan candidate worker did not complete candidate generation")
        candidate_set = next(
            item for item in comparison_step["candidate_sets"] if not item["comparison_only"]
        )
        candidate = next(item for item in candidate_set["candidates"] if item["selectable"])
        selected = client.post(
            "/api/v2/operator",
            headers=headers,
            json={
                "schema_version": "2",
                "kind": "select_candidate",
                "expected_snapshot_token": comparison_step["selection_command_token"],
                "idempotency_key": "e2e:middle:selection",
                "task_key": "jczq:2026-09-04",
                "candidate_token": candidate["candidate_token"],
                "reason": "Jun selects this deterministic comparison candidate for audit.",
            },
        )
        assert selected.status_code == 200, selected.text

        deployment = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert deployment.status_code == 200, deployment.text
        deployment_step = deployment.json()["step"]
        assert deployment_step["mode"] == "create_ticket_batch"
        created = client.post(
            "/api/v2/operator",
            headers=headers,
            json={
                "schema_version": "2",
                "kind": "create_ticket_batch",
                "expected_snapshot_token": deployment_step["command_token"],
                "idempotency_key": "e2e:middle:create-batch",
                "task_key": "jczq:2026-09-04",
                "candidate_selection_token": deployment_step["candidate_selection_token"],
            },
        )
        assert created.status_code == 200, created.text

        audit = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert audit.status_code == 200, audit.text
        audit_step = audit.json()["step"]
        if audit_step["mode"] == "adjudicate_audit_warn":
            adjudicated = client.post(
                "/api/v2/operator",
                headers=headers,
                json={
                    "schema_version": "2",
                    "kind": "adjudicate_audit_warn",
                    "expected_snapshot_token": audit_step["command_token"],
                    "idempotency_key": "e2e:middle:audit-warn",
                    "task_key": "jczq:2026-09-04",
                    "ticket_batch_token": audit_step["ticket_batch_token"],
                    "findings": [
                        {
                            "finding_token": finding["finding_token"],
                            "reason": "Jun accepts this disclosed deterministic warning.",
                            "evidence_rejected_tokens": [],
                        }
                        for finding in audit_step["findings"]
                        if finding["severity"] == "warn"
                    ],
                },
            )
            assert adjudicated.status_code == 200, adjudicated.text
            audit = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
            assert audit.status_code == 200, audit.text
            audit_step = audit.json()["step"]
        assert audit_step["mode"] == "approve_ticket_batch"
        approved = client.post(
            "/api/v2/operator",
            headers=headers,
            json={
                "schema_version": "2",
                "kind": "approve_ticket_batch",
                "expected_snapshot_token": audit_step["command_token"],
                "idempotency_key": "e2e:middle:approve-batch",
                "task_key": "jczq:2026-09-04",
                "ticket_batch_token": audit_step["ticket_batch_token"],
            },
        )
        assert approved.status_code == 200, approved.text

        ready = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        ready_work_item_key = ready.json()["active_work_item"]["work_item_key"]
        page = client.get(
            f"/operator-next/jczq/2026-09-04/{ready_work_item_key}"
        )

    assert ready.status_code == 200, ready.text
    assert ready.json()["step"]["kind"] == "await_confirmation"
    assert ready.json()["step"]["surface_version"] == "2"
    assert ready.json()["step"]["confirmation_state"] == "not_issued"
    assert ready.json()["step"]["command_token"]
    assert ready.json()["step"]["ticket_artifact_token"]
    assert page.status_code == 200, page.text
    assert "发送 Telegram 本人确认" in page.text
    assert "<pre" not in page.text
    assert _sha256(scoreboard) == scoreboard_checksum
    with fixture.engine.connect() as connection:
        domain_counts = tuple(
            int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for table in (
                sod.operator_baseline_envelope_revisions,
                sod.operator_match_judgment_revisions,
                sod.operator_judgment_prescription_revisions,
                sod.operator_candidate_generation_requests,
                sod.operator_candidate_set_revisions,
                sod.operator_candidate_selections,
                st.ticket_batch_revisions,
                st.audited_ticket_artifacts,
            )
        )
        committed_roles = connection.execute(
            select(schema.actions.c.action_type, schema.actions.c.actor_role).where(
                schema.actions.c.status == ActionStatus.COMMITTED.value
            )
        ).all()
    assert domain_counts == (1, 1, 1, 1, 2, 1, 2, 1)
    assert ("commit_operator_match_judgment", "judge_operator") in committed_roles
    assert ("generate_ticket_candidate_set", "deterministic_system") in committed_roles
    assert not any(role == "ai_analyst" for _action_type, role in committed_roles)
    assert not any(action_type == "confirm_dispatch" for action_type, _role in committed_roles)


def test_both_lanes_public_result_settlement_and_review_complete_via_real_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.ontology.operator import test_task_settlement as settlement_replay

    monkeypatch.delenv("NUTMEG_P10_REPLAY_ROOT", raising=False)
    monkeypatch.delenv("NUTMEG_PRODUCTION_DATA_DIR", raising=False)
    monkeypatch.delenv("NUTMEG_OPERATOR_TOKEN_SIGNING_KEY", raising=False)
    for lane, business_key, expected_outcomes in (
        ("jczq", "2026-09-04", 2),
        ("zucai", "26111", 14),
    ):
        root, workspace = settlement_replay._public_replay_workspace(tmp_path / lane)
        scoreboard = root / "data" / "scoreboard.json"
        scoreboard.write_bytes((FIXTURE_ROOT / "scoreboard.json").read_bytes())
        checksum = _sha256(scoreboard)
        captured_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

        if lane == "jczq":
            placed = settlement_replay._place_multimarket_jczq_ticket(
                workspace,
                result_captured_at=captured_at,
                complete_market_baseline_job=True,
            )
            engine = placed.engine
            result_document = (
                settlement_replay._jczq_multimarket_result_manifest_document(
                    task_snapshot_hash=placed.context.task_snapshot_hash,
                    captured_at=captured_at,
                )
            )
        else:
            engine, task_snapshot_hash, first_note_legs = (
                settlement_replay._place_public_zucai_ticket_set(
                    workspace,
                    complete_market_baseline_job=True,
                )
            )
            settlement_replay._seed_result_retrievals(
                engine,
                suffix="-zucai",
                captured_at=captured_at,
            )
            result_document, _void_match_id = (
                settlement_replay._zucai_result_manifest_document(
                    task_snapshot_hash=task_snapshot_hash,
                    first_note_legs=first_note_legs,
                    captured_at=captured_at,
                )
            )

        receipt = settlement_replay._invoke_public_result_ingest(
            root=root,
            manifest_name=f"{lane}-result.json",
            document=result_document,
        )
        assert receipt["outcome_count"] == expected_outcomes

        settlement_at = datetime.now(UTC)
        settled = settlement_replay._request_public_settlement(
            root=root,
            lane=lane,
            business_key=business_key,
            clock_at=settlement_at,
            idempotency_key=f"e2e:{lane}:settlement",
        )
        assert settled["step"]["request_state"] == "completed"
        assert settled["step"]["settlement_state"] == "settled"

        review_at = settlement_at + timedelta(seconds=2)
        rebuilt = CliRunner().invoke(
            cli_app,
            [
                "scoreboard",
                "rebuild-projection",
                "--data-dir",
                str(root / "data"),
                "--as-of",
                review_at.isoformat(),
                "--built-at",
                (review_at + timedelta(seconds=1)).isoformat(),
            ],
        )
        assert rebuilt.exit_code == 0, rebuilt.stdout

        services, runtime = settlement_replay._public_replay_services(
            root,
            clock_at=review_at,
        )
        app = create_product_app(
            services,
            session_secret=f"e2e-{lane}-review-session",
            csrf_secret=f"e2e-{lane}-review-csrf",
            clock=lambda review_at=review_at: review_at,
            runtime_config=runtime,
        )
        with TestClient(app) as client:
            pending = client.get(f"/api/v2/operator/tasks/{lane}/{business_key}")
            assert pending.status_code == 200, pending.text
            pending_document = pending.json()
            assert pending_document["step"]["kind"] == "review"
            assert pending_document["step"]["surface_version"] == "2"
            intervention = pending_document["step"]["intervention_quality"]
            assert intervention["effect_command_token"]

            work_item_key = pending_document["active_work_item"]["work_item_key"]
            rendered = client.get(
                f"/operator-next/{lane}/{business_key}/{work_item_key}"
            )
            assert rendered.status_code == 200, rendered.text
            assert "本期复盘" in rendered.text
            assert "<pre" not in rendered.text

            disposition = client.post(
                "/api/v2/operator",
                headers=_session_headers(client),
                json={
                    "schema_version": "2",
                    "kind": "record_scoreboard_effect_disposition",
                    "expected_snapshot_token": intervention["effect_command_token"],
                    "idempotency_key": f"e2e:{lane}:review:no-effect",
                    "task_key": f"{lane}:{business_key}",
                    "review_token": intervention["review_token"],
                    "effect": {
                        "disposition": "no_effect",
                        "metric_keys": [],
                        "reason": "本次回放没有改变治理记分牌指标。",
                    },
                },
            )
            assert disposition.status_code == 200, disposition.text

            completed = client.get(f"/api/v2/operator/tasks/{lane}/{business_key}")
            assert completed.status_code == 200, completed.text
            assert completed.json()["step"]["kind"] == "complete"
            assert completed.json()["step"]["title"] == "本期复盘已完成"

        assert _sha256(scoreboard) == checksum
        with engine.connect() as connection:
            assert connection.scalar(
                select(func.count()).select_from(sorev.operator_review_items)
            ) == 1
            assert connection.scalar(
                select(func.count()).select_from(
                    sorev.operator_scoreboard_review_completion_receipts
                )
            ) == 1
            action_roles = set(
                connection.execute(
                    select(schema.actions.c.action_type, schema.actions.c.actor_role).where(
                        schema.actions.c.action_type.in_(
                            (
                                "import_result_evidence_set",
                                "request_settlement",
                                "settle_task",
                                "materialize_operator_review_item",
                                "record_scoreboard_effect_disposition",
                            )
                        )
                    )
                ).all()
            )
        assert action_roles == {
            ("import_result_evidence_set", "deterministic_system"),
            ("request_settlement", "judge_operator"),
            ("settle_task", "deterministic_system"),
            ("materialize_operator_review_item", "deterministic_system"),
            ("record_scoreboard_effect_disposition", "judge_operator"),
        }


def test_public_effect_review_chain_completes_via_cli_api_and_lifespan_worker(
    tmp_path: Path,
) -> None:
    from tests.ontology.operator.test_review_actions import _materialized_review, _register_metric

    data_dir = tmp_path / "review" / "data"
    fixture, review_id = _materialized_review(data_dir / "ontology")
    metric_key = "operator_current_replay"
    _register_metric(fixture, metric_key)
    scoreboard = data_dir / "scoreboard.json"
    scoreboard.write_bytes((FIXTURE_ROOT / "scoreboard.json").read_bytes())
    pre_update_checksum = _sha256(scoreboard)
    first_clock = datetime(2026, 9, 5, 9, tzinfo=UTC)
    services, runtime = _review_services(
        fixture=fixture,
        data_dir=data_dir,
        tmp_path=tmp_path,
        clock_at=first_clock,
    )
    first_app = create_product_app(
        services,
        session_secret="package-twelve-review-first-session",
        csrf_secret="package-twelve-review-first-csrf",
        clock=lambda: first_clock,
        runtime_config=runtime,
    )

    with TestClient(first_app) as client:
        initial = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert initial.status_code == 200, initial.text
        initial_work_item_key = initial.json()["active_work_item"]["work_item_key"]
        initial_page = client.get(
            f"/operator-next/jczq/2026-09-04/{initial_work_item_key}"
        )
        assert initial_page.status_code == 200, initial_page.text
        assert "赛后复盘" in initial_page.text
        initial_step = initial.json()["step"]
        assert initial_step["kind"] == "review"
        initial_intervention = initial_step["intervention_quality"]
        disposition = client.post(
            "/api/v2/operator",
            headers=_session_headers(client),
            json={
                "schema_version": "2",
                "kind": "record_scoreboard_effect_disposition",
                "expected_snapshot_token": initial_intervention["effect_command_token"],
                "idempotency_key": "e2e:review:effect",
                "task_key": "jczq:2026-09-04",
                "review_token": initial_intervention["review_token"],
                "effect": {
                    "disposition": "effect_required",
                    "metric_keys": [metric_key],
                    "reason": "The current replay metric must enter governed observation.",
                },
            },
        )
        assert disposition.status_code == 200, disposition.text
        assert _sha256(scoreboard) == pre_update_checksum

        _external_scoreboard_update(scoreboard)
        post_update_checksum = _sha256(scoreboard)
        assert post_update_checksum != pre_update_checksum

        after_disposition = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert after_disposition.status_code == 200, after_disposition.text
        intervention = after_disposition.json()["step"]["intervention_quality"]
        observation = client.post(
            "/api/v2/operator",
            headers=_session_headers(client),
            json={
                "schema_version": "2",
                "kind": "record_scoreboard_observation",
                "expected_snapshot_token": intervention["observation_command_token"],
                "idempotency_key": "e2e:review:observation",
                "task_key": "jczq:2026-09-04",
                "review_token": intervention["review_token"],
                "disposition_token": intervention["disposition_token"],
                "observation": {
                    "group_key": "chains",
                    "metric_key": metric_key,
                    "tally": "1/1",
                    "detail": "The externally updated authority now records this metric.",
                    "status": "formal_manual",
                    "numerator_decimal": "1",
                    "denominator_decimal": "1",
                    "value_decimal": "1",
                    "unit": "ratio",
                    "evidence_ref_tokens": [intervention["evidence_options"][0]["token"]],
                    "effective_at": first_clock.isoformat(),
                    "supersedes_observation_token": None,
                },
            },
        )
        assert observation.status_code == 200, observation.text
        linked = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert linked.status_code == 200, linked.text
        linked_work_item_key = linked.json()["active_work_item"]["work_item_key"]
        page = client.get(
            f"/operator-next/jczq/2026-09-04/{linked_work_item_key}"
        )
        assert page.status_code == 200, page.text
        assert "赛后复盘" in page.text
        assert "{" not in page.text

    assert _sha256(scoreboard) == post_update_checksum
    with OntologyUnitOfWork(fixture.engine) as uow:
        disposition_row = uow.operator_review.current_disposition(review_id)
        assert disposition_row is not None
        links = uow.operator_review.observation_links_for_disposition(
            disposition_row.disposition_revision_id
        )
    assert len(links) == 1
    observation_id = links[0].scoreboard_observation_id

    rebuilt = CliRunner().invoke(
        cli_app,
        [
            "scoreboard",
            "rebuild-projection",
            "--data-dir",
            str(data_dir),
            "--as-of",
            "2026-09-05T09:02:00+00:00",
            "--built-at",
            "2026-09-05T09:03:00+00:00",
        ],
    )
    assert rebuilt.exit_code == 0, rebuilt.stdout
    projection = json.loads(rebuilt.stdout)
    classification_path = tmp_path / "review-classification.json"
    classification_path.write_text(
        json.dumps(
            [
                {
                    "group_key": "chains",
                    "metric_key": metric_key,
                    "classification": "formal_manual",
                    "target_ref": f"scoreboard_observation:{observation_id}",
                }
            ],
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    shadow = CliRunner().invoke(
        cli_app,
        [
            "scoreboard",
            "shadow",
            "--data-dir",
            str(data_dir),
            "--legacy-file",
            str(scoreboard),
            "--classification-file",
            str(classification_path),
            "--projection-version",
            projection["projection_version"],
            "--source-high-watermark",
            str(projection["source_high_watermark"]),
            "--requested-at",
            "2026-09-05T09:04:00+00:00",
            "--acknowledge-manual-source",
        ],
    )
    assert shadow.exit_code == 0, shadow.stdout
    shadow_receipt = json.loads(shadow.stdout)
    shadow_review_id = next(
        ref["object_id"]
        for ref in shadow_receipt["result_refs"]
        if ref["object_type"] == "scoreboard_shadow_review"
    )
    assert _sha256(scoreboard) == post_update_checksum

    completion_clock = datetime(2026, 9, 5, 9, 5, tzinfo=UTC)
    services, runtime = _review_services(
        fixture=fixture,
        data_dir=data_dir,
        tmp_path=tmp_path,
        clock_at=completion_clock,
    )
    completion_app = create_product_app(
        services,
        session_secret="package-twelve-review-completion-session",
        csrf_secret="package-twelve-review-completion-csrf",
        clock=lambda: completion_clock,
        runtime_config=runtime,
    )

    with TestClient(completion_app) as client:
        selected = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
        assert selected.status_code == 200, selected.text
        selected_intervention = selected.json()["step"]["intervention_quality"]
        ready_options = [
            option
            for option in selected_intervention["shadow_options"]
            if option["state"] == "ready"
        ]
        assert len(ready_options) == 1
        requested = client.post(
            "/api/v2/operator",
            headers=_session_headers(client),
            json={
                "schema_version": "2",
                "kind": "request_scoreboard_review_completion",
                "expected_snapshot_token": selected_intervention["completion_command_token"],
                "idempotency_key": "e2e:review:completion",
                "task_key": "jczq:2026-09-04",
                "review_token": selected_intervention["review_token"],
                "disposition_token": selected_intervention["disposition_token"],
                "shadow_review_token": ready_options[0]["token"],
            },
        )
        assert requested.status_code == 202, requested.text
        assert requested.json()["status"] == "queued"
        for _attempt in range(100):
            completed = client.get("/api/v2/operator/tasks/jczq/2026-09-04")
            assert completed.status_code == 200, completed.text
            if completed.json()["step"]["kind"] == "complete":
                break
            time.sleep(0.02)
        else:
            pytest.fail("lifespan completion worker did not complete the review")

    with OntologyUnitOfWork(fixture.engine) as uow:
        receipt = uow.operator_review.completion_receipt_for_review(review_id)
    assert receipt is not None
    assert receipt.shadow_review_id == shadow_review_id
    assert receipt.post_update_legacy_sha256 == post_update_checksum
    assert _sha256(scoreboard) == post_update_checksum


def test_rejected_actions_at_each_stage_never_advance_public_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    manifest = OfficialSaleSlateManifestV1.model_validate(_document("zucai-issue.json"))
    kernel = _seed_sale_dependencies(data_dir, (manifest,))
    monkeypatch.setattr(
        workflow_cli,
        "_now",
        lambda: datetime(2026, 9, 5, 2, 2, tzinfo=UTC),
    )
    imported = _invoke_sale(data_dir, "zucai-issue.json")
    assert imported.exit_code == 0, imported.stdout
    scoreboard = data_dir / "scoreboard.json"
    scoreboard.write_bytes((FIXTURE_ROOT / "scoreboard.json").read_bytes())
    checksum = _sha256(scoreboard)
    runtime = _runtime(data_dir, tmp_path)
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=runtime.production_data_dir,
        default_user_id="jun",
        operator_runtime_scope=runtime.runtime_scope,
        operator_surface_mode=runtime.surface_mode,
        operator_token_signing_key=SIGNING_KEY,
        operator_scheduler_enabled=False,
        telegram_bot_token=None,
    )
    services = build_product_services(settings, runtime_config=runtime)
    as_of = datetime(2026, 9, 5, 9, 30, tzinfo=UTC)
    before = services.operator_queries.task("zucai:26117", as_of=as_of)
    business_before = _business_counts(kernel.engine)
    rejected_types = (
        "request_evidence_freeze",
        "commit_operator_match_judgment",
        "request_candidate_generation",
        "approve_ticket_batch",
        "confirm_ticket_placement",
        "import_result_evidence_set",
        "request_settlement",
        "record_scoreboard_effect_disposition",
    )
    with kernel.engine.begin() as connection:
        connection.execute(
            insert(schema.actions),
            [
                {
                    "action_id": f"ACT-rejected-e2e-{index}",
                    "action_type": action_type,
                    "actor_id": "model:unauthorized",
                    "actor_role": "ai_analyst",
                    "requested_at": as_of.isoformat(),
                    "idempotency_key": f"e2e:rejected:{index}",
                    "request_hash": f"{index:064x}",
                    "expected_versions_json": "{}",
                    "payload_json": "{}",
                    "policy_version": "governance-v1",
                    "status": "rejected",
                    "result_refs_json": "[]",
                    "error_code": "permission_denied",
                    "error_detail": "injected rejected Action",
                    "committed_at": None,
                }
                for index, action_type in enumerate(rejected_types, start=1)
            ],
        )

    after = services.operator_queries.task("zucai:26117", as_of=as_of)
    app = create_product_app(
        services,
        session_secret="package-twelve-rejected-session",
        csrf_secret="package-twelve-rejected-csrf",
        clock=lambda: as_of,
        runtime_config=runtime,
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v2/operator/tasks/zucai/26117",
            params={"as_of": as_of.isoformat()},
        )
        rendered = client.get(
            "/operator-next/zucai/26117",
            params={"as_of": as_of.isoformat()},
        )

    assert response.status_code == 200, response.text
    assert rendered.status_code == 200, rendered.text
    assert after.model_dump(mode="json") == before.model_dump(mode="json")
    assert response.json()["work_items"][0]["phase"] == "prepare_evidence"
    assert _business_counts(kernel.engine) == business_before == (0,) * 8
    with kernel.engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(schema.actions)
                .where(schema.actions.c.status == "rejected")
            )
            == 8
        )
    assert _sha256(scoreboard) == checksum


def test_read_only_rollback_retains_inflight_confirmation_until_public_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.ontology.operator import test_candidate_actions as candidate_module
    from tests.ontology.operator import test_confirmation_cas as confirmation_module
    from tests.ontology.operator import test_judgment_actions as judgment_module
    from tests.ontology.operator import test_no_ticket_actions as no_ticket_module
    from tests.ontology.operator.test_confirmation_cas import _issue
    from tests.ontology.operator.test_no_ticket_actions import _artifact_fixture
    from tests.product.operator_v2 import test_confirmation_lifecycle as confirmation_replay

    root = tmp_path / "rollback"
    workspace = root / "data" / "ontology"
    workspace.mkdir(parents=True)
    base_time = datetime.now(UTC) - timedelta(minutes=1)
    for module in (
        judgment_module,
        candidate_module,
        no_ticket_module,
        confirmation_module,
    ):
        monkeypatch.setattr(module, "AT", base_time)
    fixture = _artifact_fixture(workspace, at=base_time)
    protected = confirmation_replay._protected(fixture, workspace)
    issued = _issue(protected, fixture, key="e2e:rollback:issue")
    assert issued.nonce is not None
    scoreboard = root / "data" / "scoreboard.json"
    scoreboard.write_bytes((FIXTURE_ROOT / "scoreboard.json").read_bytes())
    checksum = _sha256(scoreboard)
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.SHADOW,
        runtime_scope=OperatorRuntimeScope.PRODUCTION,
        data_dir=(root / "data").resolve(),
        production_data_dir=(root / "data").resolve(),
        running_commit="package-twelve-rollback",
    )
    settings = AppSettings(
        _env_file=None,
        data_dir=runtime.data_dir,
        production_data_dir=runtime.production_data_dir,
        default_user_id="jun",
        operator_runtime_scope=runtime.runtime_scope,
        operator_surface_mode=runtime.surface_mode,
        operator_scheduler_enabled=False,
        telegram_bot_token=None,
    )
    services = build_product_services(settings, runtime_config=runtime)
    before_counts = confirmation_replay._callback_counts(fixture.engine)
    app = create_product_app(
        services,
        session_secret="package-twelve-rollback-session",
        csrf_secret="package-twelve-rollback-csrf",
        clock=lambda: base_time + timedelta(minutes=3),
        runtime_config=runtime,
    )

    with TestClient(app) as client:
        task = client.get(
            "/api/v2/operator/tasks/jczq/2026-09-04",
            params={"as_of": (base_time + timedelta(minutes=3)).isoformat()},
        )
        page = client.get(
            "/operator-next/jczq/2026-09-04",
            params={"as_of": (base_time + timedelta(minutes=3)).isoformat()},
        )
        blocked = client.post(
            "/api/v2/operator",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )

    assert task.status_code == 200, task.text
    assert page.status_code == 200, page.text
    assert 'data-read-only="true"' in page.text
    assert blocked.status_code == 405
    assert before_counts == confirmation_replay._callback_counts(fixture.engine)
    project_root = Path(__file__).resolve().parents[2]
    plugin_path = (
        project_root / "integrations" / "openclaw" / "nutmeg-ticket-confirmation" / "index.js"
    )
    node_program = r"""
import { pathToFileURL } from "node:url";

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
const registrations = { handlers: [], services: [] };
const plugin = (await import(pathToFileURL(process.argv.at(-1)).href))
  .createNutmegTicketConfirmationPlugin();
plugin.register({
  registrationMode: "full",
  pluginConfig: input.pluginConfig,
  registerInteractiveHandler(value) { registrations.handlers.push(value); },
  registerService(value) { registrations.services.push(value); },
});
const responses = { replies: [], edits: [] };
await registrations.services[0].start({ logger: { warn() {} } });
const result = await registrations.handlers[0].handler({
  accountId: "nutmeg",
  callbackId: "e2e-rollback-callback",
  senderId: "222",
  auth: { isAuthorizedSender: true },
  callback: { data: input.callbackData, chatId: 111, messageId: 7 },
  respond: {
    async reply(value) { responses.replies.push(value); },
    async editMessage(value) { responses.edits.push(value); },
  },
});
await registrations.services[0].stop();
process.stdout.write(JSON.stringify({ result, responses }));
"""
    environment = os.environ.copy()
    environment.update(
        {
            "NUTMEG_DATA_DIR": str(root / "data"),
            "NUTMEG_PRODUCTION_DATA_DIR": str(root / "production"),
            "NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS": "111",
        }
    )
    callback = subprocess.run(  # noqa: S603 - fixed local executable and plugin fixture
        ["node", "--input-type=module", "-e", node_program, str(plugin_path)],
        cwd=project_root,
        env=environment,
        input=json.dumps(
            {
                "pluginConfig": {
                    "projectRoot": str(project_root),
                    "accountId": "nutmeg",
                    "ownerInstanceId": "openclaw-primary",
                    "allowedChatIds": ["111"],
                    "allowedSenderIds": ["222"],
                    "heartbeatIntervalSeconds": 30,
                    "leaseSeconds": 90,
                },
                "callbackData": f"ntc:{issued.nonce}",
            }
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert callback.returncode == 0, callback.stderr
    assert json.loads(callback.stdout)["result"] == {"handled": True}
    assert confirmation_replay._callback_counts(fixture.engine) == {
        "terminal": 1,
        "attestation": 1,
        "ticket": 1,
        "cash": 1,
        "placement": 1,
    }
    assert _sha256(scoreboard) == checksum
