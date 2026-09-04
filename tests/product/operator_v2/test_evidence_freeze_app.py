from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.config.settings import (
    AppSettings,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
)
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.operator_contracts import (
    EvidenceRequirementSummary,
    MatchEvidenceChecklist,
    OperatorCommandReceipt,
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    OperatorWorklistResponse,
    PrepareEvidenceStep,
    TaskProgressSummary,
)
from nutmeg.product.operator_runtime import OperatorRuntimeConfig
from nutmeg.product.wiring import build_product_services

NOW = datetime(2026, 9, 4, 10, tzinfo=UTC)
SIGNING_KEY = "package-five-real-app-signing-key"
OPAQUE_TOKEN = "opaque.signed-command-token"


class _NoCalls:
    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected service call: {name}")


class _OperatorQueries:
    def __init__(self) -> None:
        self.summary = OperatorTaskSummary(
            task_id="zucai:26116",
            lane=OperatorLane.ZUCAI,
            business_key="26116",
            title="足彩 26116",
            state=OperatorTaskState.PREPARE,
            deadline_at=NOW,
            is_actionable=True,
            next_action_label="冻结证据",
            priority_rank=0,
        )
        self.step = PrepareEvidenceStep(
            task_id=self.summary.task_id,
            title="核对本期证据",
            gate_state="complete",
            freeze_state="not_requested",
            complete_match_count=1,
            required_match_count=1,
            matches=[
                MatchEvidenceChecklist(
                    official_match_no="1",
                    match_label="水晶宫 - 曼彻斯特城",
                    complete=True,
                    completed_requirement_count=1,
                    required_requirement_count=1,
                    requirements=[
                        EvidenceRequirementSummary(
                            requirement_id="E1",
                            label="身份对齐",
                            state="complete",
                            detail="已核对",
                        )
                    ],
                )
            ],
            freeze_command_token=OPAQUE_TOKEN,
            requirement_revision_token="requirement-current",
        )

    def now(self) -> datetime:
        return NOW

    def worklist(self, *, as_of: datetime) -> OperatorWorklistResponse:
        return OperatorWorklistResponse(
            as_of=as_of,
            selected=self.summary,
            tasks=[self.summary],
        )

    def task(self, task_id: str, *, as_of: datetime) -> OperatorTaskResponse:
        assert task_id == self.summary.task_id
        return OperatorTaskResponse(
            as_of=as_of,
            mutation_token="a" * 64,
            selected=self.summary,
            alternatives=[],
            progress=TaskProgressSummary(completed=1, total=1, label="证据准备"),
            step=self.step,
        )


class _OperatorActions:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, object]] = []

    def request_evidence_freeze(self, command, *, actor_id, actor_role):
        self.calls.append((command, actor_id, actor_role))
        return OperatorCommandReceipt(
            command_kind="freeze_evidence",
            status="queued",
            task_key=command.task_key,
        )


def _runtime(tmp_path: Path, mode: OperatorSurfaceMode) -> OperatorRuntimeConfig:
    production = (tmp_path / "production").resolve()
    data_dir = (
        (tmp_path / "isolated").resolve()
        if mode is OperatorSurfaceMode.ACTIVE
        else production
    )
    return OperatorRuntimeConfig(
        surface_mode=mode,
        runtime_scope=(
            OperatorRuntimeScope.ISOLATED_CANDIDATE
            if mode is OperatorSurfaceMode.ACTIVE
            else OperatorRuntimeScope.PRODUCTION
        ),
        data_dir=data_dir,
        production_data_dir=production,
        running_commit="a" * 40,
    )


def _client(tmp_path: Path, mode: OperatorSurfaceMode) -> tuple[TestClient, _OperatorActions]:
    runtime = _runtime(tmp_path, mode)
    actions = _OperatorActions()
    services = SimpleNamespace(
        settings=SimpleNamespace(default_user_id="jun", data_dir=runtime.data_dir),
        runtime=runtime,
        queries=_NoCalls(),
        actions=_NoCalls(),
        operator_queries=_OperatorQueries(),
        operator_actions=actions,
        copilot=None,
        tickets=_NoCalls(),
    )
    app = create_product_app(
        services,
        runtime_config=runtime,
        session_secret="package-five-session",
        csrf_secret="package-five-csrf",
        clock=lambda: NOW,
    )
    return TestClient(app), actions


def _freeze_document() -> dict[str, str]:
    return {
        "schema_version": "2",
        "kind": "freeze_evidence",
        "expected_snapshot_token": OPAQUE_TOKEN,
        "idempotency_key": "browser:evidence:freeze:real-app",
        "task_key": "zucai:26116",
        "requirement_revision_token": "requirement-current",
    }


def _session_headers(client: TestClient) -> dict[str, str]:
    session = client.get("/api/v1/session")
    return {
        "X-CSRF-Token": session.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def test_active_app_mounts_real_workbench_and_dispatches_freeze(tmp_path: Path) -> None:
    client, actions = _client(tmp_path, OperatorSurfaceMode.ACTIVE)

    page = client.get("/operator-next")
    response = client.post(
        "/api/v2/operator",
        json=_freeze_document(),
        headers=_session_headers(client),
    )

    assert page.status_code == 200
    assert 'data-step-kind="prepare_evidence"' in page.text
    assert "新版工作台为只读预览" not in page.text
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert len(actions.calls) == 1


@pytest.mark.parametrize(
    "mode",
    [OperatorSurfaceMode.LEGACY_READ_ONLY, OperatorSurfaceMode.SHADOW],
)
def test_non_active_app_rejects_v2_before_parsing_body(
    tmp_path: Path,
    mode: OperatorSurfaceMode,
) -> None:
    client, actions = _client(tmp_path, mode)

    response = client.post(
        "/api/v2/operator",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 405
    assert actions.calls == []


def test_active_app_requires_session_csrf_and_same_origin(tmp_path: Path) -> None:
    client, actions = _client(tmp_path, OperatorSurfaceMode.ACTIVE)
    document = _freeze_document()

    assert client.post("/api/v2/operator", json=document).status_code == 403
    headers = _session_headers(client)
    assert (
        client.post(
            "/api/v2/operator",
            json=document,
            headers={"Origin": headers["Origin"]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v2/operator",
            json=document,
            headers={**headers, "Origin": "https://invalid.example"},
        ).status_code
        == 403
    )
    assert actions.calls == []


def test_product_wiring_installs_evidence_query_action_and_uow_gate(
    tmp_path: Path,
) -> None:
    data_dir = (tmp_path / "isolated").resolve()
    production = (tmp_path / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=production,
        operator_runtime_scope="isolated_candidate",
        operator_surface_mode="active",
        operator_token_signing_key=SIGNING_KEY,
        telegram_bot_token=None,
        operator_scheduler_enabled=False,
    )
    runtime = _runtime(tmp_path, OperatorSurfaceMode.ACTIVE)
    build_ontology_kernel(settings).initialize()

    services = build_product_services(settings, runtime_config=runtime)

    assert callable(services.operator_queries.evidence_freeze_context)
    assert services.operator_actions._evidence_actions is services.kernel.evidence_actions
    assert callable(services.kernel.evidence_actions._freeze_gate_resolver)


def test_operator_javascript_posts_v2_token_without_decoding() -> None:
    javascript = (
        Path(__file__).parents[3]
        / "nutmeg/interfaces/web/static/product/operator.js"
    ).read_text(encoding="utf-8")

    assert "snapshotHex" not in javascript
    assert 'postJson("/api/v2/operator"' in javascript
    assert "form.dataset.commandToken" in javascript
