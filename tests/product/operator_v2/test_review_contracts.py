from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.interfaces.operator_api import (
    GradePredictionCommandV2,
    RecordScoreboardEffectDispositionCommandV2,
    RecordScoreboardObservationCommandV2,
    RequestScoreboardReviewCompletionCommandV2,
    mount_operator_api,
)
from nutmeg.ontology.actions.models import (
    ActionOutcome,
    ActionStatus,
    ActorRole,
    ObjectRef,
)
from nutmeg.ontology.actions.workflow_actions import GradePredictionRequest
from nutmeg.ontology.operator.review_actions import (
    RecordScoreboardEffectDispositionRequest,
    RecordScoreboardReviewObservationRequest,
    RequestScoreboardReviewCompletionRequest,
)
from nutmeg.product.errors import ProductActionBlockedError
from nutmeg.product.operator_actions import OperatorActionService
from nutmeg.product.operator_contracts import OperatorCommandReceipt
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
    OperatorSnapshotTokenPayloadV1,
)

NOW = datetime(2026, 9, 5, 9, tzinfo=UTC)
TASK_KEY = "zucai:26116"
TOKEN_KEY = b"package-eleven-review-product-token-key"


class _Actions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, str, ActorRole]] = []

    def _record(
        self,
        kind: str,
        command: object,
        *,
        actor_id: str,
        actor_role: ActorRole,
    ) -> OperatorCommandReceipt:
        self.calls.append((kind, command, actor_id, actor_role))
        return OperatorCommandReceipt(
            command_kind=kind,
            status=("queued" if kind == "request_scoreboard_review_completion" else "completed"),
            task_key=TASK_KEY,
        )

    def grade_prediction(self, command, **authority) -> OperatorCommandReceipt:
        return self._record("grade_prediction", command, **authority)

    def record_scoreboard_effect_disposition(
        self,
        command,
        **authority,
    ) -> OperatorCommandReceipt:
        return self._record(
            "record_scoreboard_effect_disposition",
            command,
            **authority,
        )

    def record_scoreboard_observation(
        self,
        command,
        **authority,
    ) -> OperatorCommandReceipt:
        return self._record("record_scoreboard_observation", command, **authority)

    def request_scoreboard_review_completion(
        self,
        command,
        **authority,
    ) -> OperatorCommandReceipt:
        return self._record(
            "request_scoreboard_review_completion",
            command,
            **authority,
        )


def _client(actions: _Actions | None = None) -> tuple[TestClient, _Actions]:
    app = FastAPI()

    async def allow(_request) -> None:
        return None

    configured = actions or _Actions()
    mount_operator_api(
        app,
        require_mutation_session=allow,
        operator_actions=configured,
        actor_id="jun",
    )
    return TestClient(app), configured


def _command(kind: str, **fields: object) -> dict[str, object]:
    return {
        "schema_version": "2",
        "kind": kind,
        "expected_snapshot_token": f"opaque.{kind}.snapshot",
        "idempotency_key": f"browser:{kind}:1",
        "task_key": TASK_KEY,
        **fields,
    }


def _observation() -> dict[str, object]:
    return {
        "group_key": "judgment_intervention",
        "metric_key": "user_naked_wheels",
        "tally": "1/3",
        "detail": "26116 review observation",
        "status": "formal_manual",
        "numerator_decimal": "1",
        "denominator_decimal": "3",
        "value_decimal": None,
        "unit": "count",
        "evidence_ref_tokens": ["opaque.review.evidence"],
        "effective_at": NOW.isoformat(),
        "supersedes_observation_token": None,
    }


def test_review_commands_route_only_server_assigned_judge_authority() -> None:
    client, actions = _client()
    documents = (
        _command(
            "grade_prediction",
            prediction_review_token="opaque.prediction.review-item",
            outcome="hit",
            reason="赛果已经满足预注册的可证伪条件。",
        ),
        _command(
            "record_scoreboard_effect_disposition",
            review_token="opaque.operator.review",
            effect={
                "disposition": "effect_required",
                "metric_keys": ["user_naked_wheels"],
                "reason": "本次人工干预需要进入治理观察。",
            },
        ),
        _command(
            "record_scoreboard_observation",
            review_token="opaque.operator.review",
            disposition_token="opaque.scoreboard.disposition",
            observation=_observation(),
        ),
        _command(
            "request_scoreboard_review_completion",
            review_token="opaque.operator.review",
            disposition_token="opaque.scoreboard.disposition",
            shadow_review_token="opaque.signed.shadow-review",
        ),
    )

    responses = [client.post("/api/v2/operator", json=document) for document in documents]

    assert [response.status_code for response in responses] == [200, 200, 200, 202]
    assert [kind for kind, *_rest in actions.calls] == [
        "grade_prediction",
        "record_scoreboard_effect_disposition",
        "record_scoreboard_observation",
        "request_scoreboard_review_completion",
    ]
    assert all(
        actor_id == "jun" and actor_role is ActorRole.JUDGE_OPERATOR
        for _kind, _command_value, actor_id, actor_role in actions.calls
    )
    assert all(
        "actor_id" not in command.model_dump()
        and "actor_role" not in command.model_dump()
        for _kind, command, _actor_id, _actor_role in actions.calls
    )


@pytest.mark.parametrize(
    "document",
    (
        _command(
            "grade_prediction",
            prediction_review_token="opaque.prediction.review-item",
            outcome="hit",
            reason="human reason",
            prediction_id="prediction-raw-id",
        ),
        _command(
            "grade_prediction",
            prediction_review_token="opaque.prediction.review-item",
            target_type="factor_verdict",
            target_id="factor-raw-id",
            outcome="hit",
            reason="human reason",
        ),
        _command(
            "record_scoreboard_effect_disposition",
            review_token="opaque.operator.review",
            review_id="review-raw-id",
            actor_role="judge_operator",
            effect={
                "disposition": "no_effect",
                "metric_keys": [],
                "reason": "human reason",
            },
        ),
        _command(
            "record_scoreboard_observation",
            review_token="opaque.operator.review",
            disposition_token="opaque.scoreboard.disposition",
            observation={**_observation(), "action_id": "action-raw-id"},
        ),
        _command(
            "record_scoreboard_observation",
            review_token="opaque.operator.review",
            disposition_token="opaque.scoreboard.disposition",
            observation={"payload": _observation()},
        ),
        _command(
            "request_scoreboard_review_completion",
            review_token="opaque.operator.review",
            disposition_token="opaque.scoreboard.disposition",
            shadow_review_token="opaque.signed.shadow-review",
            legacy_sha256="a" * 64,
        ),
        _command(
            "grade_review_item",
            review_token="opaque.operator.review",
            target={"kind": "factor_verdict", "outcome": "active"},
        ),
        _command(
            "record_factor_lifecycle",
            factor_token="opaque.factor",
            status="active",
        ),
    ),
)
def test_review_commands_reject_raw_ids_authority_generic_targets_and_mappings(
    document: dict[str, object],
) -> None:
    client, actions = _client()

    response = client.post("/api/v2/operator", json=document)

    assert response.status_code == 422
    assert actions.calls == []


@pytest.mark.parametrize(
    "document",
    (
        _command(
            "grade_prediction",
            prediction_review_token="opaque.prediction.review-item",
            outcome="miss",
        ),
        _command(
            "grade_prediction",
            prediction_review_token="opaque.prediction.review-item",
            outcome="miss",
            reason="   ",
        ),
        _command(
            "record_scoreboard_effect_disposition",
            review_token="opaque.operator.review",
            effect={"disposition": "no_effect", "metric_keys": []},
        ),
        _command(
            "record_scoreboard_effect_disposition",
            review_token="opaque.operator.review",
            effect={
                "disposition": "effect_required",
                "metric_keys": [],
                "reason": "human reason",
            },
        ),
        _command(
            "record_scoreboard_effect_disposition",
            review_token="opaque.operator.review",
            effect={
                "disposition": "no_effect",
                "metric_keys": ["user_naked_wheels"],
                "reason": "human reason",
            },
        ),
        _command(
            "record_scoreboard_effect_disposition",
            review_token="opaque.operator.review",
            effect={
                "disposition": "effect_required",
                "metric_keys": ["user_naked_wheels", "user_naked_wheels"],
                "reason": "human reason",
            },
        ),
    ),
)
def test_review_commands_require_human_reason_and_closed_effect_shape(
    document: dict[str, object],
) -> None:
    client, actions = _client()

    response = client.post("/api/v2/operator", json=document)

    assert response.status_code == 422
    assert actions.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("numerator_decimal", "NaN"),
        ("denominator_decimal", -1),
        ("value_decimal", {"raw": 1}),
        ("evidence_ref_tokens", []),
        ("effective_at", "2026-09-05T09:00:00"),
    ),
)
def test_scoreboard_observation_has_typed_decimal_evidence_and_time_fields(
    field: str,
    value: object,
) -> None:
    client, actions = _client()
    observation = _observation()
    observation[field] = value

    response = client.post(
        "/api/v2/operator",
        json=_command(
            "record_scoreboard_observation",
            review_token="opaque.operator.review",
            disposition_token="opaque.scoreboard.disposition",
            observation=observation,
        ),
    )

    assert response.status_code == 422
    assert actions.calls == []


def _snapshot_token(
    kind: OperatorCommandKind,
    *,
    projection_high_watermark: int = 7,
) -> str:
    return OperatorSnapshotTokenCodec(TOKEN_KEY).encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash="b" * 64,
            work_item_id="zucai:26116:review:current",
            command_kind=kind,
            dependency_revision_ids=[
                "review:review-internal-1",
                f"scoreboard_projection:{projection_high_watermark}",
            ],
        )
    )


def _grade_snapshot_token() -> str:
    return OperatorSnapshotTokenCodec(TOKEN_KEY).encode(
        OperatorSnapshotTokenPayloadV1(
            task_snapshot_hash="b" * 64,
            work_item_id="zucai:26116:review:current",
            command_kind=OperatorCommandKind.GRADE_PREDICTION,
            dependency_revision_ids=["prediction:prediction-internal-1"],
        )
    )


class _ReviewQueries:
    @staticmethod
    def now() -> datetime:
        return NOW

    def prediction_grade_context(
        self,
        task_key: str,
        expected_snapshot_token: str,
        *,
        as_of: datetime,
    ):
        assert task_key == TASK_KEY
        assert as_of == NOW
        assert expected_snapshot_token == _grade_snapshot_token()
        return SimpleNamespace(
            task_key=TASK_KEY,
            task_snapshot_hash="b" * 64,
            work_item_id="zucai:26116:review:current",
            dependency_revision_ids=("prediction:prediction-internal-1",),
            prediction_refs_by_token=(
                ("opaque.prediction.review-item", "prediction-internal-1"),
            ),
        )

    def scoreboard_review_context(
        self,
        task_key: str,
        command_kind: OperatorCommandKind,
        expected_snapshot_token: str,
        *,
        as_of: datetime,
    ):
        assert task_key == TASK_KEY
        assert as_of == NOW
        submitted = OperatorSnapshotTokenCodec(TOKEN_KEY).decode(
            expected_snapshot_token
        )
        assert submitted.command_kind is command_kind
        assert submitted.work_item_id == "zucai:26116:review:current"
        return SimpleNamespace(
            task_key=TASK_KEY,
            task_snapshot_hash="b" * 64,
            work_item_id="zucai:26116:review:current",
            dependency_revision_ids=(
                "review:review-internal-1",
                "scoreboard_projection:7",
            ),
            review_id="review-internal-1",
            review_token="opaque.operator.review",
            disposition_revision_id="disposition-internal-1",
            disposition_token="opaque.scoreboard.disposition",
            evidence_refs_by_token=(
                ("opaque.review.evidence", ObjectRef("prediction", "prediction-internal-1")),
            ),
            observation_refs_by_token=(),
            command_kind=command_kind,
        )


class _ProjectionRepository:
    def __init__(self, state: str = "available") -> None:
        self.state = state

    def scoreboard_projection(self, *, as_of: str) -> dict[str, object]:
        assert as_of == NOW.isoformat()
        return {
            "health": {
                "state": self.state,
                "source_high_watermark": 7,
            },
            "rows": [],
        }


class _WorkflowActions:
    def __init__(self) -> None:
        self.requests: list[GradePredictionRequest] = []

    def grade_prediction(self, request: GradePredictionRequest) -> ActionOutcome:
        self.requests.append(request)
        return ActionOutcome(
            action_id="action-grade-prediction",
            action_type="grade_prediction",
            status=ActionStatus.COMMITTED,
            result_refs=(ObjectRef("prediction", request.prediction_id),),
        )


class _ReviewDomainActions:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def _committed(self, request: object, action_type: str) -> ActionOutcome:
        self.requests.append(request)
        return ActionOutcome(
            action_id=f"action-{action_type}",
            action_type=action_type,
            status=ActionStatus.COMMITTED,
            result_refs=(ObjectRef("operator_review_item", "review-internal-1"),),
        )

    def record_scoreboard_effect_disposition(self, request) -> ActionOutcome:
        return self._committed(request, "record_scoreboard_effect_disposition")

    def record_scoreboard_review_observation(self, request) -> ActionOutcome:
        return self._committed(request, "record_scoreboard_observation")

    def request_scoreboard_review_completion(self, request) -> ActionOutcome:
        return self._committed(request, "request_scoreboard_review_completion")


def _service(
    tmp_path: Path,
    *,
    projection_state: str = "available",
) -> tuple[OperatorActionService, _WorkflowActions, _ReviewDomainActions]:
    scoreboard = tmp_path / "scoreboard.json"
    scoreboard.write_text('{"authority":"legacy"}\n', encoding="utf-8")
    workflow = _WorkflowActions()
    review = _ReviewDomainActions()
    return (
        OperatorActionService(
            queries=_ReviewQueries(),
            action_gateway=SimpleNamespace(),
            workflow_actions=workflow,
            review_actions=review,
            snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
            repository=_ProjectionRepository(projection_state),
            scoreboard_path=scoreboard,
            clock=lambda: NOW,
        ),
        workflow,
        review,
    )


def test_prediction_grade_does_not_gain_a_scoreboard_projection_dependency(
    tmp_path: Path,
) -> None:
    service, workflow, review = _service(tmp_path, projection_state="stale")
    command = GradePredictionCommandV2(
        schema_version="2",
        kind="grade_prediction",
        expected_snapshot_token=_grade_snapshot_token(),
        idempotency_key="browser:grade-prediction:1",
        task_key=TASK_KEY,
        prediction_review_token="opaque.prediction.review-item",
        outcome="hit",
        reason="赛果满足预注册条件。",
    )

    receipt = service.grade_prediction(
        command,
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert receipt.command_kind == "grade_prediction"
    assert len(workflow.requests) == 1
    assert workflow.requests[0] == GradePredictionRequest(
        prediction_id="prediction-internal-1",
        outcome="hit",
        reason="赛果满足预注册条件。",
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="browser:grade-prediction:1",
        requested_at=NOW,
    )
    assert review.requests == []


def _effect_command(high_watermark: int = 7) -> RecordScoreboardEffectDispositionCommandV2:
    return RecordScoreboardEffectDispositionCommandV2(
        schema_version="2",
        kind="record_scoreboard_effect_disposition",
        expected_snapshot_token=_snapshot_token(
            OperatorCommandKind.RECORD_SCOREBOARD_EFFECT_DISPOSITION,
            projection_high_watermark=high_watermark,
        ),
        idempotency_key="browser:review-effect:1",
        task_key=TASK_KEY,
        review_token="opaque.operator.review",
        effect={
            "disposition": "effect_required",
            "metric_keys": ["user_naked_wheels"],
            "reason": "人工干预需要形成观察。",
        },
    )


def _observation_command() -> RecordScoreboardObservationCommandV2:
    return RecordScoreboardObservationCommandV2(
        schema_version="2",
        kind="record_scoreboard_observation",
        expected_snapshot_token=_snapshot_token(
            OperatorCommandKind.RECORD_SCOREBOARD_OBSERVATION,
        ),
        idempotency_key="browser:review-observation:1",
        task_key=TASK_KEY,
        review_token="opaque.operator.review",
        disposition_token="opaque.scoreboard.disposition",
        observation=_observation(),
    )


def _completion_command() -> RequestScoreboardReviewCompletionCommandV2:
    return RequestScoreboardReviewCompletionCommandV2(
        schema_version="2",
        kind="request_scoreboard_review_completion",
        expected_snapshot_token=_snapshot_token(
            OperatorCommandKind.REQUEST_SCOREBOARD_REVIEW_COMPLETION,
        ),
        idempotency_key="browser:review-completion:1",
        task_key=TASK_KEY,
        review_token="opaque.operator.review",
        disposition_token="opaque.scoreboard.disposition",
        shadow_review_token="opaque.signed.shadow-review",
    )


@pytest.mark.parametrize(
    ("method_name", "command"),
    (
        ("record_scoreboard_effect_disposition", _effect_command()),
        ("record_scoreboard_observation", _observation_command()),
        ("request_scoreboard_review_completion", _completion_command()),
    ),
)
def test_each_scoreboard_review_control_returns_projection_stale(
    tmp_path: Path,
    method_name: str,
    command: object,
) -> None:
    service, workflow, review = _service(tmp_path, projection_state="stale")

    with pytest.raises(ProductActionBlockedError) as caught:
        getattr(service, method_name)(
            command,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    assert caught.value.code == "projection_stale"
    assert workflow.requests == []
    assert review.requests == []


def test_effect_disposition_uses_server_review_and_scoreboard_hash(tmp_path: Path) -> None:
    service, _workflow, review = _service(tmp_path)

    receipt = service.record_scoreboard_effect_disposition(
        _effect_command(),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert receipt.command_kind == "record_scoreboard_effect_disposition"
    assert len(review.requests) == 1
    request = review.requests[0]
    assert isinstance(request, RecordScoreboardEffectDispositionRequest)
    assert request.review_id == "review-internal-1"
    assert request.expected_disposition_revision_id == "disposition-internal-1"
    assert request.pre_update_legacy_sha256 == (
        "570fc798bf90d4119a93d5662f91a9e9d4d452908ab8c7a44f990b17c9f9a885"
    )


def test_observation_resolves_only_allowlisted_evidence_tokens(tmp_path: Path) -> None:
    service, _workflow, review = _service(tmp_path)

    receipt = service.record_scoreboard_observation(
        _observation_command(),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert receipt.command_kind == "record_scoreboard_observation"
    assert len(review.requests) == 1
    request = review.requests[0]
    assert isinstance(request, RecordScoreboardReviewObservationRequest)
    assert request.review_id == "review-internal-1"
    assert request.expected_disposition_revision_id == "disposition-internal-1"
    assert request.observation.evidence_refs == [
        ObjectRef("prediction", "prediction-internal-1")
    ]
    assert request.observation.actor_id == "jun"
    assert request.observation.actor_role is ActorRole.JUDGE_OPERATOR


def test_completion_queues_the_exact_submitted_shadow_token(tmp_path: Path) -> None:
    service, _workflow, review = _service(tmp_path)

    receipt = service.request_scoreboard_review_completion(
        _completion_command(),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )

    assert receipt.status == "queued"
    assert len(review.requests) == 1
    request = review.requests[0]
    assert isinstance(request, RequestScoreboardReviewCompletionRequest)
    assert request.review_id == "review-internal-1"
    assert request.expected_disposition_revision_id == "disposition-internal-1"
    assert request.shadow_review_token == "opaque.signed.shadow-review"


def test_projection_rebuild_requires_a_fresh_review_snapshot_token(tmp_path: Path) -> None:
    service, _workflow, review = _service(tmp_path)

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        service.record_scoreboard_effect_disposition(
            _effect_command(high_watermark=6),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
        )

    assert caught.value.code == "task_snapshot_changed"
    assert review.requests == []

    receipt = service.record_scoreboard_effect_disposition(
        _effect_command(high_watermark=7),
        actor_id="jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
    )
    assert receipt.status == "completed"
    assert len(review.requests) == 1
