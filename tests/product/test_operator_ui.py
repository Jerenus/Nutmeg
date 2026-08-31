import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.operator_contracts import (
    BlockedStep,
    BusinessEvidenceSummary,
    ConstructTicketStep,
    JudgeMatchesStep,
    OperatorLane,
    OperatorRecoverySummary,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    OperatorWorklistResponse,
    PrescriptionDifferenceSummary,
    TaskProgressSummary,
    TicketVersionSummary,
    WaitingDataStep,
)

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)


class FakeOperatorQueries:
    def __init__(self, state: str = "judge_matches", *, empty: bool = False) -> None:
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
        if self.summary.state is OperatorTaskState.JUDGE_MATCHES:
            step = JudgeMatchesStep(
                task_id=task_id,
                item_key="ADJ-1",
                title="任九档位",
                prompt="当前需要你处理",
                options=["R432", "V288"],
                evidence=[
                    BusinessEvidenceSummary(
                        label="资金",
                        value="V288=72%帽内",
                        freshness_label="14:00",
                    )
                ],
            )
        elif self.summary.state is OperatorTaskState.CONSTRUCT_TICKET:
            step = ConstructTicketStep(
                task_id=task_id,
                prescription={"12": "31", "13": "3"},
                candidates=[
                    TicketVersionSummary(
                        candidate_id="R432",
                        label="R432",
                        faces={"12": "3", "13": "31"},
                        notes=216,
                        cost_yuan=432,
                        p_all=0.2796,
                        expected_broken=1.65,
                        within_cap=False,
                        common_dead_faces=["场 4: 0"],
                        prescription_differences=[
                            PrescriptionDifferenceSummary(
                                match_no=12,
                                prescribed_faces="31",
                                candidate_faces="3",
                            ),
                            PrescriptionDifferenceSummary(
                                match_no=13,
                                prescribed_faces="3",
                                candidate_faces="31",
                            ),
                        ],
                    )
                ],
            )
        elif self.summary.state is OperatorTaskState.BLOCKED:
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
    return _client(m2_product_services, FakeOperatorQueries("waiting_data"))


@pytest.fixture
def invalid_source(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries("blocked"))


@pytest.fixture
def client_with_resolved_adj(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries("construct_ticket"))


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


def test_judgment_state_shows_business_evidence_and_one_action(client: TestClient) -> None:
    html = client.get("/tasks/zucai:26112").text

    assert 'data-step-kind="judge_matches"' in html
    assert "当前需要你处理" in html
    assert "任九档位" in html
    assert "V288=72%帽内" in html
    assert html.count('class="primary-action"') == 1
    assert 'data-action="resolve-issue-adjudication"' in html
    assert 'name="actor_id"' not in html
    assert 'name="actor_role"' not in html
    assert "payload_json" not in html


def test_ticket_state_is_a_business_table_not_rx_json(
    client_with_resolved_adj: TestClient,
) -> None:
    html = client_with_resolved_adj.get("/tasks/zucai:26112").text

    assert 'data-step-kind="construct_ticket"' in html
    assert "版本" in html and "注数" in html and "票价" in html
    assert "P(全对)" in html and "期望断腿" in html
    assert "R432" in html
    assert 'data-action="select-ticket-version"' in html
    assert "ticket_versions" not in html
    assert "human note; not parsed" not in html
    assert "{" not in html
    assert html.count('data-deviation-match="') == 2
    assert 'data-deviation-rules required' in html
    assert 'data-deviation-reason required' in html
    assert 'type="radio" name="candidate_id"' in html


def test_operator_forms_escape_content_and_require_governed_fields(client: TestClient) -> None:
    html = client.get("/tasks/zucai:26112").text
    assert '<script>alert("fixture")</script>' not in html
    assert "&lt;script&gt;" in html
    assert 'name="reason"' in html
    assert 'name="selected_option"' in html
    assert "更新于" in html
    assert re.search(r"action-[0-9a-f]{8}", html) is None
    assert re.search(r"\b[0-9a-f]{64}\b", html) is None
    assert html.count('class="primary-action"') == 1


def test_operator_javascript_only_collects_forms(client: TestClient) -> None:
    script = client.get("/assets/product/operator.js").text
    assert "/adjudications" in script
    assert "/candidate" in script
    for forbidden in (
        "optimize",
        "p_all *",
        "expected_broken =",
        "audit_legs",
        "deployment gate",
        "capital_utilization =",
        "median_bonus =",
        "odds *",
        "fair *",
        "priority",
    ):
        assert forbidden not in script
