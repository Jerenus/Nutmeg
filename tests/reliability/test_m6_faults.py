import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Timer

import httpx
import pytest
from fastapi.testclient import TestClient

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.workflow_actions import RecordAdjudicationRequest
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.copilot import (
    PortkeyCopilotProvider,
    ProductCopilotResponseError,
    ProductCopilotUnavailableError,
)
from nutmeg.product.operator_runtime import (
    OperatorRuntimeConfig,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
)
from nutmeg.product.repository import ProductReadRepository
from nutmeg.product.wiring import build_product_services
from nutmeg.reliability import backup as backup_module
from nutmeg.reliability.backup import create_backup
from nutmeg.reliability.contracts import FAULT_SCENARIOS, validate_fault_matrix

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _provider(content: str | None = None, *, timeout: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if timeout:
            raise httpx.ReadTimeout("injected timeout", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    return PortkeyCopilotProvider(
        base_url="https://provider.test/v1",
        api_key="fixture-secret",
        model="fixture-model",
        client=httpx.Client(
            base_url="https://provider.test/v1",
            transport=httpx.MockTransport(handler),
        ),
    )


def _provider_timeout(_root: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    with pytest.raises(ProductCopilotUnavailableError):
        _provider(timeout=True).investigate({"evidence_handling": "untrusted"})
    return "retryable", "transport timeout mapped to a secret-safe unavailable result"


def _partial_provider_response(
    _root: Path, _monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    with pytest.raises(ProductCopilotResponseError):
        _provider("{}").investigate({"evidence_handling": "untrusted"})
    return "blocked", "incomplete draft rejected before ontology mutation"


def _invalid_provider_schema(
    _root: Path, _monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    injected = {
        "summary": "attempted authority injection",
        "scenarios": [],
        "proposed_belief": None,
        "factors": [],
        "falsifier": None,
        "citations": [],
        "conflicts": [],
        "missing_evidence": [],
        "actor_role": "judge_operator",
    }
    with pytest.raises(ProductCopilotResponseError):
        _provider(json.dumps(injected)).investigate(
            {"evidence_handling": "untrusted"}
        )
    return "blocked", "strict response schema rejected injected authority fields"


def _kernel(root: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=root / "data"))
    kernel.initialize()
    return kernel


def _sqlite_lock(root: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    kernel = _kernel(root)
    locker = sqlite3.connect(kernel.paths.database, check_same_thread=False)
    locker.execute("BEGIN IMMEDIATE")
    release = Timer(0.05, locker.commit)
    release.start()
    try:
        outcome = kernel.workflow.record_adjudication(
            RecordAdjudicationRequest(
                subject_type="release_drill",
                subject_id="sqlite-lock",
                decision="hold",
                reason="prove bounded SQLite writer contention",
                evidence_rejected=[],
                alternative={},
                supersedes_adjudication_id=None,
                actor_id="operator:owner",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="m6:fault:sqlite-lock",
                requested_at=NOW,
            )
        )
    finally:
        release.join(timeout=2)
        locker.close()
    assert outcome.status is ActionStatus.COMMITTED
    assert kernel.status().integrity_check == "ok"
    return "retryable", "writer waited for bounded lock release and committed atomically"


def _process_interruption(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    kernel = _kernel(root)
    destination = root / "interrupted-backup"

    def interrupt(_staging: Path, _destination: Path) -> None:
        raise OSError("injected process interruption")

    monkeypatch.setattr(backup_module, "_atomic_publish", interrupt)
    with pytest.raises(OSError, match="process interruption"):
        create_backup(
            kernel,
            destination,
            requested_at=NOW,
            acknowledge_writers_stopped=True,
        )
    assert not destination.exists()
    assert not list(root.glob(".interrupted-backup.staging-*"))
    assert kernel.status().integrity_check == "ok"
    return "blocked", "interrupted publication left no partial backup or state corruption"


def _duplicate_action(root: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    kernel = _kernel(root)
    request = ArtifactIngestRequest(
        content=b'{"fault":"duplicate-action"}',
        content_type="application/json",
        source_name="m6-fault",
        source_type="fixture",
        actor_id="source:m6-fault",
        actor_role=ActorRole.CONNECTOR,
        idempotency_key="m6:fault:duplicate-action",
        retrieved_at=NOW,
    )
    first = kernel.artifact_ingest.ingest(request)
    second = kernel.artifact_ingest.ingest(request)
    assert second.action_id == first.action_id
    assert kernel.status().action_counts == {"committed": 1}
    return "retryable", "idempotent replay returned the committed winner exactly once"


def _sse_disconnect(root: Path, _monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    # SSE 只推送**投影已消费**的事件（`projection_signals.delivered_sequence`，
    # 2026-09-10 双泳道重构引入的读己所写闸）。推进该游标的 `ProductOutboxWorker`
    # 只在 `runtime_config` 非空时才被装配，且只活在 `infrastructure_workers.
    # lifespan` 里。因此本探针必须①带 operator runtime 建 services ②用 `with
    # TestClient(...)` 触发 lifespan。缺任一条件，流恒为空——
    # 本测试 2026-08-24 写就、闸 2026-09-10 才加，此后一直红在这里。
    # ⚠️不要靠删掉那个闸来修：无工人时隐藏事件是**设计意图**，
    # `tests/product/operator_v2/test_infrastructure_consumers.py` 显式断言了它。
    data_dir = (root / "data").resolve()
    production_dir = (root / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=production_dir,
        operator_surface_mode="active",
        operator_runtime_scope="isolated_candidate",
        operator_token_signing_key="m6-sse-probe-signing-key-32-bytes!",
    )
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    first = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=b"first",
            content_type="text/plain",
            source_name="m6-sse",
            source_type="fixture",
            actor_id="source:m6-sse",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="m6:fault:sse:first",
            retrieved_at=NOW,
        )
    )
    assert first.status is ActionStatus.COMMITTED
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=data_dir,
        production_data_dir=production_dir,
        running_commit="m6-sse-probe",
    )
    services = build_product_services(settings, runtime_config=runtime)
    assert services.infrastructure_workers is not None, "无工人则无人推进投递游标"
    app = create_product_app(
        services,
        session_secret="m6-sse-probe-session",
        csrf_secret="m6-sse-probe-csrf",
        clock=lambda: NOW,
        runtime_config=runtime,
    )
    with TestClient(app) as client:
        cursor = client.get("/api/v1/events?after=0&limit=100").json()["next_cursor"]
        kernel.artifact_ingest.ingest(
            ArtifactIngestRequest(
                content=b"second",
                content_type="text/plain",
                source_name="m6-sse",
                source_type="fixture",
                actor_id="source:m6-sse",
                actor_role=ActorRole.CONNECTOR,
                idempotency_key="m6:fault:sse:second",
                retrieved_at=NOW,
            )
        )
        # 条件变量等待，不是 sleep 轮询：后台工人投递到 cursor 之后即返回。
        assert services.projection_signals.wait_for_delivery(
            after=cursor, timeout_seconds=10.0
        ), "投影工人未在 10s 内投递第二条事件"
        resumed = client.get(f"/api/v1/events/stream?after={cursor}&once=true")
    assert resumed.status_code == 200
    assert f"id: {cursor + 1}" in resumed.text
    assert f"id: {cursor}\n" not in resumed.text
    return "retryable", "reconnect resumed strictly after the durable event cursor"


def _projection_interruption(
    root: Path, _monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    kernel = _kernel(root)
    first = kernel.calibrate.build(
        CalibrateRequest(as_of=NOW.isoformat(), built_at=NOW.isoformat())
    )
    assert first.status == "succeeded"
    kernel.paths.analytics.unlink()
    repository = ProductReadRepository(kernel.engine, kernel.paths.analytics)
    degraded = repository.scoreboard_projection(as_of=NOW.isoformat())
    assert degraded["health"]["state"] == "unavailable"
    assert not kernel.paths.analytics.exists()
    rebuilt = kernel.calibrate.build(
        CalibrateRequest(
            as_of=NOW.isoformat(),
            built_at="2026-08-24T12:01:00+00:00",
        )
    )
    assert rebuilt.status == "succeeded"
    assert kernel.paths.analytics.is_file()
    assert kernel.status().integrity_check == "ok"
    return "degraded", "missing projection degraded explicitly and rebuilt from SQLite"


PROBES = {
    "provider_timeout": _provider_timeout,
    "partial_provider_response": _partial_provider_response,
    "invalid_provider_schema": _invalid_provider_schema,
    "sqlite_lock": _sqlite_lock,
    "process_interruption": _process_interruption,
    "duplicate_action": _duplicate_action,
    "sse_disconnect": _sse_disconnect,
    "projection_interruption": _projection_interruption,
}


def test_fault_matrix_is_built_only_from_executed_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert tuple(PROBES) == FAULT_SCENARIOS
    scenarios = []
    for scenario, probe in PROBES.items():
        outcome, observed = probe(tmp_path / scenario, monkeypatch)
        scenarios.append(
            {
                "scenario": scenario,
                "test_ref": (
                    "tests/reliability/test_m6_faults.py::"
                    f"test_fault_matrix_is_built_only_from_executed_probes#{scenario}"
                ),
                "observed_result": observed,
                "outcome": outcome,
                "state_corruption": False,
            }
        )

    report = {
        "schema_version": "fault-v1",
        "candidate_commit": "abc123",
        "policy_version": "release-v1",
        "scenarios": scenarios,
    }
    assert validate_fault_matrix(report).passed is True
