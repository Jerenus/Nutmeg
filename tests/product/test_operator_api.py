from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.contracts import ProductActionResponse
from nutmeg.product.operator_contracts import (
    ConstructTicketStep,
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    OperatorWorklistResponse,
    TaskProgressSummary,
    TelegramConfirmationDispatch,
    TicketVersionSummary,
)

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)
TOKEN = "a" * 64


class FakeOperatorQueries:
    def __init__(self) -> None:
        self.summary = OperatorTaskSummary(
            task_id="zucai:26112",
            lane=OperatorLane.ZUCAI,
            business_key="26112",
            title="足彩 26112",
            state=OperatorTaskState.CONSTRUCT_TICKET,
            is_actionable=True,
            next_action_label="比较候选票",
            priority_rank=0,
        )
        self.step = ConstructTicketStep(
            task_id="zucai:26112",
            prescription={"1": "3"},
            candidates=[
                TicketVersionSummary(
                    candidate_id="R432",
                    label="R432",
                    faces={"1": "3"},
                    notes=1,
                    cost_yuan=2,
                    p_all=0.5,
                    expected_broken=0.5,
                )
            ],
        )

    def worklist(self, *, as_of):
        return OperatorWorklistResponse(as_of=as_of, selected=self.summary, tasks=[self.summary])

    def task(self, task_id: str, *, as_of):
        return OperatorTaskResponse(
            as_of=as_of,
            mutation_token=TOKEN,
            selected=self.summary,
            alternatives=[],
            progress=TaskProgressSummary(completed=1, total=1, label="比较票版"),
            step=self.step,
        )


class FakeOperatorActions:
    def __init__(self) -> None:
        self.calls = []

    def _committed(self, method, task_id, command, **identity):
        self.calls.append((method, task_id, command, identity))
        return ProductActionResponse(
            action_id=f"action-{method}",
            action_type="record_adjudication",
            status="committed",
            committed_at=NOW.isoformat(),
        )

    def resolve_issue_adjudication(self, task_id, command, **identity):
        return self._committed("adjudication", task_id, command, **identity)

    def select_ticket_version(self, task_id, command, **identity):
        return self._committed("candidate", task_id, command, **identity)

    def record_deployment(self, task_id, command, **identity):
        return self._committed("deployment", task_id, command, **identity)

    def request_telegram_confirmation(self, task_id, command, **identity):
        self.calls.append(("telegram", task_id, command, identity))
        return TelegramConfirmationDispatch(
            ticket_artifact_id="tat-1",
            confirmation_id="confirmation-1",
            expires_at=NOW,
            dispatch_state="dry_run",
            message_preview="fixture",
        )

    def grade_prediction(self, task_id, command, **identity):
        return self._committed("grade", task_id, command, **identity)


@pytest.fixture
def operator_actions() -> FakeOperatorActions:
    return FakeOperatorActions()


@pytest.fixture
def client(m3_product_services, operator_actions) -> TestClient:
    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=m3_product_services.queries,
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=None,
        tickets=SimpleNamespace(),
        operator_queries=FakeOperatorQueries(),
        operator_actions=operator_actions,
    )
    return TestClient(
        create_product_app(
            services,
            session_secret="operator-api-session",
            csrf_secret="operator-api-csrf",
            clock=lambda: NOW,
        )
    )


def _session(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def _payloads():
    common = {"expected_snapshot_token": TOKEN, "idempotency_key": "operator:1"}
    return [
        (
            "/api/v1/operator/tasks/zucai:26112/adjudications",
            {
                **common,
                "adjudication_key": "ADJ-1",
                "decision": "keep",
                "reason": "fixture",
            },
        ),
        (
            "/api/v1/operator/tasks/zucai:26112/candidate",
            {**common, "candidate_id": "R432", "reason": "fixture", "deviations": []},
        ),
        (
            "/api/v1/operator/tasks/zucai:26112/deployment",
            {**common, "candidate_id": "R432", "decision": "keep", "reason": "fixture"},
        ),
        (
            "/api/v1/operator/tasks/jczq:2026-08-28/telegram-confirmation",
            {**common, "dry_run": True},
        ),
        (
            "/api/v1/operator/tasks/zucai:26112/grade-prediction",
            {
                **common,
                "prediction_id": "prediction-p1",
                "outcome": "hit",
                "reason": "official result",
            },
        ),
    ]


def test_operator_get_routes_publish_strict_v1_contract(client: TestClient) -> None:
    worklist = client.get("/api/v1/operator/tasks")
    task = client.get("/api/v1/operator/tasks/zucai:26112")

    assert worklist.status_code == 200
    assert worklist.json()["schema_version"] == "1"
    assert task.status_code == 200
    assert task.json()["step"]["kind"] == "construct_ticket"
    assert "action_id" not in task.json()


@pytest.mark.parametrize(("path", "payload"), _payloads())
def test_every_legacy_operator_mutation_is_retired_before_parsing(
    client: TestClient,
    operator_actions: FakeOperatorActions,
    path: str,
    payload: dict,
) -> None:
    assert client.post(path, content=b"not-json").status_code == 405
    headers = _session(client)
    assert (
        client.post(path, json=payload, headers={"Origin": headers["Origin"]}).status_code
        == 405
    )
    assert (
        client.post(
            path,
            json=payload,
            headers={**headers, "Origin": "https://evil.example"},
        ).status_code
        == 405
    )
    assert client.post(path, json=payload, headers=headers).status_code == 405
    assert operator_actions.calls == []


def test_actor_spoofing_cannot_reach_retired_facade(
    client: TestClient, operator_actions: FakeOperatorActions
) -> None:
    path, payload = _payloads()[1]
    response = client.post(
        path,
        json={**payload, "actor_role": "ai_analyst"},
        headers=_session(client),
    )

    assert response.status_code == 405
    assert operator_actions.calls == []


def test_retired_api_does_not_inject_or_call_owner_identity(
    client: TestClient, operator_actions: FakeOperatorActions
) -> None:
    path, payload = _payloads()[1]
    response = client.post(path, json=payload, headers=_session(client))

    assert response.status_code == 405
    assert operator_actions.calls == []


def test_openapi_lists_narrow_operator_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/operator/tasks",
        "/api/v1/operator/tasks/{task_id}",
        "/api/v1/operator/tasks/{task_id}/adjudications",
        "/api/v1/operator/tasks/{task_id}/candidate",
        "/api/v1/operator/tasks/{task_id}/deployment",
        "/api/v1/operator/tasks/{task_id}/telegram-confirmation",
        "/api/v1/operator/tasks/{task_id}/grade-prediction",
    ):
        assert path in paths
