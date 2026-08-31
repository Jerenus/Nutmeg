import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.operator_contracts import (
    AuditDeploymentStep,
    AwaitResultStep,
    BlockedStep,
    BusinessEvidenceSummary,
    CompleteStep,
    ConfirmationStep,
    ConstructTicketStep,
    JudgeMatchesStep,
    LedgerStep,
    OperatorLane,
    OperatorRecoverySummary,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    OperatorWorklistResponse,
    PrescriptionDifferenceSummary,
    ReviewItemSummary,
    ReviewStep,
    TaskProgressSummary,
    TicketVersionSummary,
    WaitingDataStep,
)

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)


class FakeOperatorQueries:
    def __init__(
        self,
        state: str = "judge_matches",
        *,
        empty: bool = False,
        audit_state: str = "pass",
        deployment_state: str = "pass",
        confirmation_state: str = "not_issued",
        placement_state: str = "unplaced",
    ) -> None:
        self.empty = empty
        self.audit_state = audit_state
        self.deployment_state = deployment_state
        self.confirmation_state = confirmation_state
        self.placement_state = placement_state
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
        lane_value, business_key = task_id.split(":", 1)
        selected = self.summary.model_copy(
            update={
                "task_id": task_id,
                "lane": OperatorLane(lane_value),
                "business_key": business_key,
            }
        )
        if self.summary.state is OperatorTaskState.AWAIT_CONFIRMATION:
            step = ConfirmationStep(
                task_id=task_id,
                ticket_artifact_id="tat-1",
                amount=100,
                currency="CNY",
                deadline_at=NOW + timedelta(hours=2),
                confirmation_state=self.confirmation_state,
                confirmation_expires_at=(
                    NOW + timedelta(minutes=5)
                    if self.confirmation_state == "open"
                    else None
                ),
            )
        elif self.summary.state is OperatorTaskState.AWAIT_LEDGER:
            step = LedgerStep(
                task_id=task_id,
                ticket_artifact_id="tat-1",
                placement_state=self.placement_state,
                amount=100,
                currency="CNY",
                external_reference="telegram:fixture",
            )
        elif self.summary.state is OperatorTaskState.AWAIT_RESULT:
            step = AwaitResultStep(
                task_id=task_id,
                title="等待权威赛果",
                expected_at=NOW + timedelta(hours=4),
            )
        elif self.summary.state is OperatorTaskState.COMPLETE:
            step = CompleteStep(
                task_id=task_id,
                title="本日流程已完成",
                summary=(
                    "未确认，按未出票处理；没有入账"
                    if self.placement_state == "shadow"
                    else "流程已完成"
                ),
            )
        elif self.summary.state is OperatorTaskState.AUDIT_DEPLOYMENT:
            allowed = (
                ["drop_match", "change_structure", "empty_position"]
                if self.deployment_state == "reduce_or_empty"
                else ["keep", "change_structure"]
            )
            step = AuditDeploymentStep(
                task_id=task_id,
                candidate=TicketVersionSummary(
                    candidate_id="R432",
                    label="R432",
                    faces={"1": "310"},
                    notes=216,
                    cost_yuan=432,
                    p_all=0.2796,
                    expected_broken=1.65,
                ),
                gate_candidate_id="V288",
                gate_candidate_cost_yuan=288,
                audit_state=self.audit_state,
                findings=[
                    BusinessEvidenceSummary(
                        label="C8",
                        value='<img src=x onerror=alert("finding")>',
                        severity="warn",
                    )
                ],
                deployment_state=self.deployment_state,
                capital_utilization=0.72,
                median_bonus=4098,
                break_even_to_median=0.94,
                allowed_decisions=allowed,
            )
        elif self.summary.state is OperatorTaskState.REVIEW:
            step = ReviewStep(
                task_id=task_id,
                hit_count=1,
                total_count=2,
                stake_yuan=100,
                payout_yuan=160,
                pnl_yuan=60,
                calibration_summary="赛后结果已登记",
                current_item=ReviewItemSummary(
                    item_type="prediction",
                    item_id="prediction-p1",
                    title="至少一场平",
                    evidence=[
                        BusinessEvidenceSummary(
                            label="证伪条件", value="全无平局"
                        )
                    ],
                    allowed_outcomes=["hit", "miss", "na"],
                ),
            )
        elif self.summary.state is OperatorTaskState.JUDGE_MATCHES:
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
            selected=selected,
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


@pytest.fixture
def client_at_gate(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries("audit_deployment"))


@pytest.fixture
def client_at_reduce_or_empty_gate(m2_product_services) -> TestClient:
    return _client(
        m2_product_services,
        FakeOperatorQueries("audit_deployment", deployment_state="reduce_or_empty"),
    )


@pytest.fixture
def gate_client_factory(m2_product_services):
    def factory(audit_state: str) -> TestClient:
        return _client(
            m2_product_services,
            FakeOperatorQueries("audit_deployment", audit_state=audit_state),
        )

    return factory


@pytest.fixture
def client_with_artifact(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries("await_confirmation"))


@pytest.fixture
def client_with_shadow(m2_product_services) -> TestClient:
    return _client(
        m2_product_services,
        FakeOperatorQueries("complete", placement_state="shadow"),
    )


@pytest.fixture
def confirmation_client(m2_product_services):
    def factory(state: str) -> TestClient:
        return _client(
            m2_product_services,
            FakeOperatorQueries("await_confirmation", confirmation_state=state),
        )

    return factory


@pytest.fixture
def await_result_client(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries("await_result"))


@pytest.fixture
def review_client(m2_product_services) -> TestClient:
    return _client(m2_product_services, FakeOperatorQueries("review"))


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


def test_deployment_view_translates_gate_without_defaulting_empty(
    client_at_gate: TestClient,
) -> None:
    html = client_at_gate.get("/tasks/zucai:26112").text

    assert 'data-step-kind="audit_deployment"' in html
    assert "票面审计" in html
    assert "资金使用率" in html
    assert "中位奖金" in html
    assert "回本/中位" in html
    assert "需要你的部署裁决" in html
    assert 'value="keep"' in html
    assert 'value="empty_position"' not in html
    assert "系统建议空仓" not in html
    assert html.count('class="primary-action"') == 1


def test_empty_position_appears_only_for_explicit_gate_failure(
    client_at_reduce_or_empty_gate: TestClient,
) -> None:
    html = client_at_reduce_or_empty_gate.get("/tasks/zucai:26112").text

    assert 'value="empty_position"' in html
    assert "部署门未通过" in html


@pytest.mark.parametrize(
    ("audit_state", "label"),
    [("pass", "PASS"), ("warn", "WARN"), ("error", "ERROR")],
)
def test_audit_labels_are_textual_and_findings_are_escaped(
    gate_client_factory, audit_state, label
) -> None:
    html = gate_client_factory(audit_state).get("/tasks/zucai:26112").text
    assert label in html
    assert "C8" in html
    assert 'href="/tasks/zucai:26112"' in html
    assert '<img src=x onerror=alert("finding")>' not in html
    assert '"exit_code"' not in html


def test_deployment_javascript_posts_only_governed_fields(client_at_gate: TestClient) -> None:
    script = client_at_gate.get("/assets/product/operator.js").text
    assert "/deployment" in script
    assert "record-deployment" in script


def test_confirmation_state_has_one_owner_dispatch_action(
    client_with_artifact: TestClient,
) -> None:
    html = client_with_artifact.get("/tasks/jczq:2026-08-28").text

    assert 'data-step-kind="await_confirmation"' in html
    assert "票面与金额已锁定" in html
    assert "Telegram 本人确认" in html
    assert "入账确认" in html
    assert 'data-action="request-telegram-confirmation"' in html
    assert "ConfirmDispatch" not in html
    assert "nonce" not in html
    assert "ticket_hash" not in html


def test_shadow_is_explained_as_not_placed(client_with_shadow: TestClient) -> None:
    html = client_with_shadow.get("/tasks/jczq:2026-08-28").text

    assert "未确认，按未出票处理" in html
    assert "没有入账" in html
    assert "ticket_shadow_records" not in html


@pytest.mark.parametrize(
    ("state", "text", "has_send"),
    [
        ("not_issued", "发送 Telegram 本人确认", True),
        ("open", "等待你在 Telegram 点击", False),
        ("expired", "确认已过期", True),
    ],
)
def test_confirmation_states(confirmation_client, state, text, has_send) -> None:
    html = confirmation_client(state).get("/tasks/jczq:2026-08-28").text
    assert text in html
    assert ('data-action="request-telegram-confirmation"' in html) is has_send
    assert "receipt_content" not in html


def test_await_result_refreshes_without_exposing_ledger_payload(
    await_result_client: TestClient,
) -> None:
    html = await_result_client.get("/tasks/jczq:2026-08-28").text
    assert 'data-auto-refresh="waiting"' in html
    assert "预计结果时间" in html
    assert "cash_transactions" not in html


def test_review_shows_one_prediction_and_requires_owner_grade(
    review_client: TestClient,
) -> None:
    html = review_client.get("/tasks/zucai:26112").text

    assert 'data-step-kind="review"' in html
    assert "命中 1 / 2" in html
    assert "本金 ¥100" in html
    assert "返还 ¥160" in html
    assert "盈亏 +¥60" in html
    assert "至少一场平" in html
    assert "全无平局" in html
    assert 'data-action="grade-prediction"' in html
    assert html.count('class="primary-action"') == 1
    assert 'name="outcome" value="hit"' in html
    assert 'name="outcome" value="miss"' in html
    assert 'name="outcome" value="na"' in html
    assert 'name="reason"' in html
    assert 'name="outcome" value="hit" checked' not in html
    assert "概率" not in html
