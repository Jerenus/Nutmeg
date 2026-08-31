import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.operator_contracts import (
    BlockedStep,
    OperatorLane,
    OperatorRecoverySummary,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    OperatorWorklistResponse,
    TaskProgressSummary,
    WaitingDataStep,
)

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)


class FakeOperatorQueries:
    def __init__(self, state: str = "waiting_data", *, empty: bool = False) -> None:
        self.empty = empty
        self.summary = OperatorTaskSummary(
            task_id="zucai:26112",
            lane=OperatorLane.ZUCAI,
            business_key="26112",
            title='足彩 26112 <script>alert("fixture")</script>',
            state=OperatorTaskState(state),
            deadline_at=NOW + timedelta(hours=12),
            waiting_until=NOW + timedelta(minutes=30),
            is_actionable=False,
            next_action_label="查看当前状态",
            priority_rank=0,
            block_reason_code="source_contract_invalid" if state == "blocked" else None,
        )

    def worklist(self, *, as_of):
        return OperatorWorklistResponse(
            as_of=as_of,
            selected=None if self.empty else self.summary,
            tasks=[] if self.empty else [self.summary],
        )

    def task(self, task_id: str, *, as_of):
        if self.summary.state is OperatorTaskState.BLOCKED:
            step = BlockedStep(
                task_id=task_id,
                title="数据需要修复",
                recovery=OperatorRecoverySummary(
                    code="source_contract_invalid",
                    missing="有效数据",
                    impact="不能继续",
                    action_label="重新检查",
                ),
            )
        else:
            step = WaitingDataStep(
                task_id=task_id,
                title="等待下一批数据",
                recovery=OperatorRecoverySummary(
                    code="waiting_for_source",
                    missing="下午数据",
                    impact="当前无需操作",
                    action_label="到时刷新",
                    retry_at=NOW + timedelta(minutes=30),
                ),
            )
        return OperatorTaskResponse(
            as_of=as_of,
            mutation_token="a" * 64,
            selected=self.summary,
            alternatives=[],
            progress=TaskProgressSummary(completed=0, total=1, label="当前需要你处理"),
            step=step,
        )


def _client(m2_product_services, operator_queries) -> TestClient:
    services = SimpleNamespace(
        kernel=m2_product_services.kernel,
        queries=m2_product_services.queries,
        actions=m2_product_services.actions,
        settings=m2_product_services.settings,
        copilot=None,
        tickets=SimpleNamespace(),
        operator_queries=operator_queries,
        operator_actions=SimpleNamespace(),
    )
    return TestClient(
        create_product_app(
            services,
            session_secret="operator-ui-session",
            csrf_secret="operator-ui-csrf",
            clock=lambda: NOW,
        )
    )


@pytest.fixture
def client(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries())


@pytest.fixture
def no_tasks(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries(empty=True))


@pytest.fixture
def waiting(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries())


@pytest.fixture
def invalid_source(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries("blocked"))


def test_root_opens_selected_task_without_system_chrome(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'data-workspace="operator-task"' in response.text
    assert "足彩 26112" in response.text
    assert "当前需要你处理" in response.text
    assert "Schema" not in response.text
    assert "Outbox" not in response.text
    assert "Action ID" not in response.text
    assert "本体浏览" not in response.text
    assert 'href="/tasks"' in response.text
    assert 'href="/system"' in response.text


def test_system_index_contains_old_tools_without_owning_root(client: TestClient) -> None:
    system = client.get("/system")
    legacy = client.get("/system/command-center?date=2026-08-28")

    assert system.status_code == 200
    assert 'data-workspace="system-maintenance"' in system.text
    assert 'href="/system/command-center"' in system.text
    assert 'href="/system/operations"' in system.text
    assert 'href="/system/ontology"' in system.text
    assert legacy.status_code == 200
    assert 'data-workspace="command-center"' in legacy.text

    alias = client.get("/system/operations")
    compatibility = client.get("/operations")
    assert alias.status_code == compatibility.status_code == 200
    assert 'data-workspace="operations"' in alias.text


@pytest.mark.parametrize(
    ("fixture_name", "marker"),
    [
        ("no_tasks", 'data-empty-state="operator-tasks"'),
        ("waiting", 'data-step-kind="waiting_data"'),
        ("invalid_source", 'data-step-kind="blocked"'),
    ],
)
def test_root_designed_states(request, fixture_name, marker) -> None:
    client = request.getfixturevalue(fixture_name)
    response = client.get("/")
    assert response.status_code == 200
    assert marker in response.text


def test_shell_is_semantic_local_and_escaped(client: TestClient) -> None:
    html = client.get("/").text
    assert 'class="skip-link" href="#main-content"' in html
    assert all(tag in html for tag in ("<header", "<nav", "<main"))
    assert 'href="/tasks"' in html
    assert '<script>alert("fixture")</script>' not in html
    assert not re.search(r'(?:src|href)="https?://', html)
    assert client.get("/assets/product/operator.css").status_code == 200
    assert client.get("/assets/product/operator.js").status_code == 200
