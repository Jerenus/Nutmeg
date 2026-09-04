from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.operator_api import (
    FreezeEvidenceCommandV2,
    RebuildScoreboardProjectionCommandV2,
    mount_operator_api,
)
from nutmeg.ontology.actions.models import ActionOutcome, ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.operator.evidence_actions import RequestEvidenceFreezeRequest
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product.actions import ProductActionGateway
from nutmeg.product.operator_actions import (
    OperatorActionService,
    scoreboard_projection_snapshot,
)
from nutmeg.product.operator_contracts import OperatorCommandReceipt
from nutmeg.product.operator_evidence import (
    EvidenceFreezeCommandContext,
    OperatorDependencyLeaves,
)
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
    OperatorSnapshotTokenPayloadV1,
)
from nutmeg.product.repository import ProductReadRepository

NOW = datetime(2026, 9, 4, 9, tzinfo=UTC)
KEY = b"package-five-api-signing-key-is-long-enough"


class _Actions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, str, ActorRole]] = []

    def request_evidence_freeze(self, command, *, actor_id, actor_role):
        payload = OperatorSnapshotTokenCodec(KEY).decode(
            command.expected_snapshot_token
        )
        if payload.command_kind is not OperatorCommandKind.FREEZE_EVIDENCE:
            raise OperatorSnapshotTokenError("invalid_request")
        self.calls.append(("freeze", command, actor_id, actor_role))
        return OperatorCommandReceipt(
            command_kind="freeze_evidence",
            status="queued",
            task_key=command.task_key,
            source_high_watermark=None,
            projection_high_watermark=None,
        )

    def rebuild_scoreboard_projection(self, command, *, actor_id, actor_role):
        payload = OperatorSnapshotTokenCodec(KEY).decode(
            command.expected_snapshot_token
        )
        if payload.command_kind is not OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION:
            raise OperatorSnapshotTokenError("invalid_request")
        self.calls.append(("rebuild", command, actor_id, actor_role))
        return OperatorCommandReceipt(
            command_kind="rebuild_scoreboard_projection",
            status="completed",
            task_key=None,
            source_high_watermark=12,
            projection_high_watermark=12,
        )


def _token(kind: OperatorCommandKind) -> str:
    return OperatorSnapshotTokenCodec(KEY).encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash="b" * 64,
            work_item_id="zucai:26116:evidence",
            command_kind=kind,
            dependency_revision_ids=["requirement:req-1", "slate:slate-1"],
        )
    )


def _client(actions: _Actions) -> TestClient:
    app = FastAPI()

    async def allow(_request) -> None:
        return None

    mount_operator_api(
        app,
        require_mutation_session=allow,
        operator_actions=actions,
        actor_id="jun",
    )
    return TestClient(app)


def _freeze_document(**updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "2",
        "kind": "freeze_evidence",
        "expected_snapshot_token": _token(OperatorCommandKind.FREEZE_EVIDENCE),
        "idempotency_key": "browser:evidence:freeze:1",
        "task_key": "zucai:26116",
        "requirement_revision_token": "req-1",
    }
    document.update(updates)
    return document


def test_freeze_command_is_strict_and_queues_only_a_server_owned_judge_request() -> None:
    actions = _Actions()
    client = _client(actions)

    response = client.post("/api/v2/operator", json=_freeze_document())

    assert response.status_code == 202
    assert response.json() == {
        "schema_version": "1",
        "command_kind": "freeze_evidence",
        "status": "queued",
        "task_key": "zucai:26116",
        "source_high_watermark": None,
        "projection_high_watermark": None,
    }
    assert len(actions.calls) == 1
    kind, command, actor_id, actor_role = actions.calls[0]
    assert kind == "freeze"
    assert command.task_key == "zucai:26116"
    assert actor_id == "jun"
    assert actor_role is ActorRole.JUDGE_OPERATOR

    for field in ("actor_id", "actor_role", "request_id", "bundle_ids", "policy_version"):
        rejected = client.post(
            "/api/v2/operator",
            json=_freeze_document(**{field: "browser-controlled"}),
        )
        assert rejected.status_code == 422
    assert len(actions.calls) == 1


def test_freeze_rejects_cross_command_token_and_unknown_business_fields() -> None:
    client = _client(_Actions())

    wrong_token = client.post(
        "/api/v2/operator",
        json=_freeze_document(
            expected_snapshot_token=_token(
                OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION
            )
        ),
    )
    unknown = client.post(
        "/api/v2/operator",
        json=_freeze_document(raw_payload={"role": "deterministic_system"}),
    )

    assert wrong_token.status_code == 422
    assert wrong_token.json()["code"] == "invalid_request"
    assert unknown.status_code == 422


def test_stale_freeze_command_returns_a_stable_refresh_link() -> None:
    class StaleActions(_Actions):
        def request_evidence_freeze(self, command, *, actor_id, actor_role):
            raise OperatorSnapshotTokenError("task_snapshot_changed")

    client = _client(StaleActions())

    response = client.post("/api/v2/operator", json=_freeze_document())

    assert response.status_code == 409
    assert response.json()["code"] == "task_snapshot_changed"
    assert response.json()["details"] == {"recovery_href": "/operator-next"}


def test_projection_rebuild_is_a_separate_build_only_command(tmp_path: Path) -> None:
    scoreboard = tmp_path / "scoreboard.json"
    scoreboard.write_text('{"authority":"legacy"}\n', encoding="utf-8")
    before = hashlib.sha256(scoreboard.read_bytes()).hexdigest()
    actions = _Actions()
    client = _client(actions)
    document = {
        "schema_version": "2",
        "kind": "rebuild_scoreboard_projection",
        "expected_snapshot_token": _token(
            OperatorCommandKind.REBUILD_SCOREBOARD_PROJECTION
        ),
        "idempotency_key": "browser:scoreboard:rebuild:1",
    }

    response = client.post("/api/v2/operator", json=document)

    assert response.status_code == 200
    assert response.json()["source_high_watermark"] == 12
    assert response.json()["projection_high_watermark"] == 12
    assert hashlib.sha256(scoreboard.read_bytes()).hexdigest() == before
    assert actions.calls[0][0] == "rebuild"
    assert client.post(
        "/api/v2/operator",
        json={**document, "action_type": "record_scoreboard_observation"},
    ).status_code == 422


class _FreezeQueries:
    def __init__(self, context: EvidenceFreezeCommandContext) -> None:
        self.context = context

    def now(self) -> datetime:
        return NOW

    def evidence_freeze_context(self, task_key: str, *, as_of: datetime):
        assert task_key == self.context.task_key
        assert as_of == NOW
        return self.context


class _EvidenceActions:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def request_evidence_freeze(self, request):
        self.requests.append(request)
        return ActionOutcome(
            action_id="action-request-freeze",
            action_type="request_evidence_freeze",
            status=ActionStatus.COMMITTED,
            result_refs=(ObjectRef("operator_evidence_freeze_request", "request-1"),),
            committed_at=NOW.isoformat(),
        )


def _freeze_context() -> EvidenceFreezeCommandContext:
    leaves = OperatorDependencyLeaves(
        slate_revision_ids=("slate-1",),
        offer_state_tokens=("offer-1:open",),
        requirement_revision_ids=("req-1",),
    )
    return EvidenceFreezeCommandContext(
        task_key="zucai:26116",
        lane="zucai",
        business_key="26116",
        task_snapshot_hash="b" * 64,
        requirement_revision_token="req-1",
        ready=True,
        dependency_leaves=leaves,
    )


def test_action_service_verifies_current_freeze_context_and_delegates_one_request() -> None:
    context = _freeze_context()
    codec = OperatorSnapshotTokenCodec(KEY)
    token = codec.encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash=context.task_snapshot_hash,
            work_item_id="zucai:26116:evidence",
            command_kind=OperatorCommandKind.FREEZE_EVIDENCE,
            dependency_revision_ids=list(
                context.dependency_leaves.token_revision_ids()
            ),
        )
    )
    evidence_actions = _EvidenceActions()
    service = OperatorActionService(
        queries=_FreezeQueries(context),
        action_gateway=SimpleNamespace(),
        evidence_actions=evidence_actions,
        snapshot_tokens=codec,
    )

    result = service.request_evidence_freeze(
        FreezeEvidenceCommandV2(
            schema_version="2",
            kind="freeze_evidence",
            expected_snapshot_token=token,
            idempotency_key="browser:freeze:real-service",
            task_key="zucai:26116",
            requirement_revision_token="req-1",
        ),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert result.status == "queued"
    assert len(evidence_actions.requests) == 1
    request = evidence_actions.requests[0]
    assert request.task_family_id == "zucai:26116"
    assert request.requirement_revision_token == "req-1"
    assert request.actor_id == "jun"
    assert request.actor_role is ActorRole.JUDGE_OPERATOR
    assert not hasattr(request, "freeze_bundle_action_ids")


def test_real_projection_rebuild_changes_no_action_or_scoreboard_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir, _env_file=None))
    kernel.initialize()
    scoreboard = data_dir / "scoreboard.json"
    scoreboard.write_text('{"authority":"legacy"}\n', encoding="utf-8")
    checksum_before = hashlib.sha256(scoreboard.read_bytes()).hexdigest()
    repository = ProductReadRepository(kernel.engine, kernel.paths.analytics)
    rejected = kernel.evidence_actions.request_evidence_freeze(
        RequestEvidenceFreezeRequest(
            task_family_id="zucai:26116",
            lane="zucai",
            business_key="26116",
            requirement_revision_token="requirement-current",
            actor_id="ai",
            actor_role=ActorRole.AI_ANALYST,
            idempotency_key="projection:advance-action-high-water",
            requested_at=NOW,
        )
    )
    assert rejected.status is ActionStatus.REJECTED
    high_water_before = repository.action_high_watermark()
    assert high_water_before > 0
    build_calls: list[CalibrateRequest] = []
    real_build = kernel.calibrate.build

    def record_build(request: CalibrateRequest):
        build_calls.append(request)
        return real_build(request)

    monkeypatch.setattr(kernel.calibrate, "build", record_build)
    codec = OperatorSnapshotTokenCodec(KEY)
    payload = scoreboard_projection_snapshot(high_water_before)
    token = codec.encode(payload)
    service = OperatorActionService(
        queries=SimpleNamespace(),
        action_gateway=ProductActionGateway(kernel, repository),
        snapshot_tokens=codec,
        calibrate=kernel.calibrate,
        repository=repository,
        scoreboard_path=scoreboard,
        clock=lambda: NOW,
    )

    result = service.rebuild_scoreboard_projection(
        RebuildScoreboardProjectionCommandV2(
            schema_version="2",
            kind="rebuild_scoreboard_projection",
            expected_snapshot_token=token,
            idempotency_key="browser:rebuild:real-service",
        ),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert result.status == "completed"
    assert result.source_high_watermark == high_water_before
    assert result.projection_high_watermark == high_water_before
    assert len(build_calls) == 1
    assert isinstance(build_calls[0], CalibrateRequest)
    assert repository.action_high_watermark() == high_water_before
    assert hashlib.sha256(scoreboard.read_bytes()).hexdigest() == checksum_before


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_generic_operator_mutation_methods_remain_unavailable(method: str) -> None:
    client = _client(_Actions())
    response = client.request(method, "/api/v2/operator", json=_freeze_document())
    assert response.status_code == 405
