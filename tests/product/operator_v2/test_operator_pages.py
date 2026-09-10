from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.operator_contracts import (
    ConfirmationStep,
    JudgeMatchesStep,
    OfficialOfferViewV1,
    OfficialSaleSlateViewV1,
    OperatorLane,
    OperatorLaneResponseV1,
    OperatorMaintenanceResponseV1,
    OperatorTaskDetailV1,
    OperatorTaskSummaryV1,
    OperatorTodayResponseV1,
    OperatorWorkItemViewV1,
    TelegramOwnerStatusV1,
    TelegramTransportStatusV1,
    TodayWorkItemViewV1,
    WorkItemActionViewV1,
    WorkItemProgressViewV1,
)
from nutmeg.product.operator_runtime import validate_operator_runtime

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)
COMMIT = "b" * 40
SECRET_SNAPSHOT = "opaque-secret-snapshot-token"
RAW_ARTIFACT_ID = "ticket-artifact-db-row-001"
CONFIRM_COMMAND_TOKEN = "opaque-confirmation-command-token"
ARTIFACT_TOKEN = f"opaque.{RAW_ARTIFACT_ID}.signed"


class _NoCalls:
    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected service call: {name}")


def _progress() -> WorkItemProgressViewV1:
    return WorkItemProgressViewV1(
        completed_count=2,
        required_count=14,
        progress_label="已完成 2 / 14 场",
    )


def _action() -> WorkItemActionViewV1:
    return WorkItemActionViewV1(
        action_code="judge_matches",
        action_label="继续逐场裁决",
        enabled=True,
        recovery_link="/operator-next/zucai/26116",
    )


def _slate(
    business_key: str,
    *,
    state: str = "current",
) -> OfficialSaleSlateViewV1:
    offer = OfficialOfferViewV1(
        official_match_no="001",
        match_label="水晶宫 vs 曼彻斯特城",
        competition_label="英格兰足总杯",
        kickoff_at=NOW + timedelta(hours=4),
        sale_opens_at=NOW - timedelta(hours=2),
        sale_deadline_at=NOW + timedelta(hours=3),
        offer_state="open",
        markets=[],
        evidence_complete_count=2,
        evidence_required_count=6,
        next_action="补齐证据后裁决",
    )
    return OfficialSaleSlateViewV1(
        lane=OperatorLane.ZUCAI,
        business_key=business_key,
        revision_no=3,
        state=state,
        published_at=NOW - timedelta(hours=3),
        retrieved_at=NOW - timedelta(minutes=5),
        next_deadline_at=offer.sale_deadline_at,
        total_offer_count=1,
        open_offer_count=1,
        offers=[offer],
    )


def _task(
    business_key: str,
    *,
    task_state: str = "current",
) -> OperatorTaskSummaryV1:
    return OperatorTaskSummaryV1(
        lane=OperatorLane.ZUCAI,
        business_key=business_key,
        task_label=f"胜负彩 {business_key} 期",
        task_state=task_state,
        current_slate=_slate(
            business_key,
            state="current" if task_state == "current" else "superseded",
        ),
        work_items=[
            OperatorWorkItemViewV1(
                work_item_key="sale-wave-opaque0001",
                scope_kind="sale_wave",
                scope_label="本期 14 场",
                phase="judge_matches",
                deployment_outcome="pending",
                next_deadline_at=NOW + timedelta(hours=3),
                is_current=task_state == "current",
                snapshot_token=SECRET_SNAPSHOT,
                progress=_progress(),
                blocking_reason=None,
                next_action=_action() if task_state == "current" else None,
                audit_href="/operator-next/audit/opaque-audit-token",
            )
        ],
    )


def _task_detail(task: OperatorTaskSummaryV1) -> OperatorTaskDetailV1:
    return OperatorTaskDetailV1(
        as_of=NOW,
        task_id=f"{task.lane.value}:{task.business_key}",
        lane=task.lane,
        business_key=task.business_key,
        task_label=task.task_label,
        task_state=task.task_state,
        current_slate=task.current_slate,
        work_items=task.work_items,
        active_work_item=task.work_items[0],
        step=JudgeMatchesStep(
            task_id=f"{task.lane.value}:{task.business_key}",
            item_key="match-001",
            title="水晶宫 vs 曼彻斯特城",
            prompt="逐场判断已经登记。",
            options=[],
            mode="prescription_ready",
            completed_match_count=1,
            required_match_count=1,
            prescription_command_token="opaque-prescription-command",
            judgment_revision_tokens=["opaque-judgment-revision"],
        ),
    )


def _confirmation_detail(
    task: OperatorTaskSummaryV1,
    *,
    confirmation_state: str,
) -> OperatorTaskDetailV1:
    work_item = OperatorWorkItemViewV1.model_validate(
        {
            **task.work_items[0].model_dump(mode="python"),
            "phase": "await_confirmation",
        }
    )
    requestable = confirmation_state == "not_issued"
    return OperatorTaskDetailV1(
        as_of=NOW,
        task_id=f"{task.lane.value}:{task.business_key}",
        lane=task.lane,
        business_key=task.business_key,
        task_label=task.task_label,
        task_state=task.task_state,
        current_slate=task.current_slate,
        work_items=[work_item],
        active_work_item=work_item,
        step=ConfirmationStep(
            surface_version="2",
            task_id=f"{task.lane.value}:{task.business_key}",
            ticket_artifact_id=None,
            amount=None,
            amount_minor=172_800,
            currency="CNY",
            deadline_at=NOW + timedelta(hours=3),
            confirmation_state=confirmation_state,
            confirmation_expires_at=(
                NOW - timedelta(minutes=1)
                if confirmation_state == "expired"
                else None
            ),
            command_token=CONFIRM_COMMAND_TOKEN if requestable else None,
            ticket_artifact_token=ARTIFACT_TOKEN if requestable else None,
        ),
    )


class _OperatorQueries:
    def __init__(self) -> None:
        self.current = _task("26116")
        self.archive = _task("26115", task_state="archive")

    def today(self, *, as_of: datetime) -> OperatorTodayResponseV1:
        entry = TodayWorkItemViewV1(
            lane=OperatorLane.ZUCAI,
            business_key="26116",
            task_label="胜负彩 26116 期",
            scope_kind="sale_wave",
            scope_label="本期 14 场",
            phase="judge_matches",
            deployment_outcome="pending",
            next_deadline_at=NOW + timedelta(hours=3),
            progress=_progress(),
            blocking_reason=None,
            next_action=_action(),
        )
        return OperatorTodayResponseV1(as_of=as_of, next_action=entry, entries=[entry])

    def lane(self, lane: OperatorLane, *, as_of: datetime) -> OperatorLaneResponseV1:
        assert lane is OperatorLane.ZUCAI
        return OperatorLaneResponseV1(
            lane=lane,
            as_of=as_of,
            focus_business_key="26116",
            current_tasks=[self.current],
            archive_tasks=[self.archive],
        )

    def task_v2(
        self,
        lane: OperatorLane,
        business_key: str,
        *,
        as_of: datetime,
    ) -> OperatorTaskDetailV1:
        del as_of
        assert lane is OperatorLane.ZUCAI
        if business_key == "26116":
            return _task_detail(self.current)
        return _task_detail(self.archive)

    def work_item_v2(
        self,
        lane: OperatorLane,
        business_key: str,
        work_item_key: str,
        *,
        as_of: datetime,
    ) -> OperatorTaskDetailV1:
        detail = self.task_v2(lane, business_key, as_of=as_of)
        assert detail.active_work_item.work_item_key == work_item_key
        return detail

    def maintenance(self, *, as_of: datetime) -> OperatorMaintenanceResponseV1:
        return OperatorMaintenanceResponseV1(
            as_of=as_of,
            diagnostic_state="diagnostic_unavailable",
            diagnostic_code="diagnostic_unavailable",
            claims=[],
            stages=[],
            telegram_owner=TelegramOwnerStatusV1(
                owner_mode="unavailable",
                configured=False,
                heartbeat_state="unavailable",
                confirmation_available=False,
                blocking_code="telegram_owner_unavailable",
                recovery_label="检查 OpenClaw 确认服务",
            ),
            telegram_transport=TelegramTransportStatusV1(
                state="diagnostic_unavailable"
            ),
            recovery_label="重新检查本机运行状态",
        )


class _ConfirmationQueries(_OperatorQueries):
    def __init__(self, confirmation_state: str) -> None:
        super().__init__()
        self.confirmation_state = confirmation_state

    def task_v2(
        self,
        lane: OperatorLane,
        business_key: str,
        *,
        as_of: datetime,
    ) -> OperatorTaskDetailV1:
        del as_of
        assert lane is OperatorLane.ZUCAI
        task = self.current if business_key == "26116" else self.archive
        return _confirmation_detail(
            task,
            confirmation_state=self.confirmation_state,
        )


def _client(
    tmp_path: Path,
    *,
    mode: str = "shadow",
    operator_queries=None,
) -> TestClient:
    production = (tmp_path / "production").resolve()
    data_dir = (
        (tmp_path / "isolated").resolve()
        if mode == "active"
        else production
    )
    runtime_values = (
        {
            "operator_accepted_commit": COMMIT,
            "operator_token_signing_key": "operator-page-signing-key-32-bytes",
        }
        if mode == "active"
        else {}
    )
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=production,
        operator_runtime_scope=(
            "isolated_candidate" if mode == "active" else "production"
        ),
        operator_surface_mode=mode,
        candidate_commit=COMMIT,
        **runtime_values,
    )
    runtime = validate_operator_runtime(
        settings,
        running_commit=COMMIT,
        dirty=False,
        data_dir_was_explicit=mode == "active",
    )
    services = SimpleNamespace(
        settings=settings,
        runtime=runtime,
        queries=_NoCalls(),
        actions=_NoCalls(),
        operator_queries=operator_queries or _OperatorQueries(),
        operator_actions=None,
        copilot=_NoCalls(),
        tickets=_NoCalls(),
    )
    return TestClient(
        create_product_app(
            services,
            runtime_config=runtime,
            session_secret="operator-page-session",
            csrf_secret="operator-page-csrf",
            clock=lambda: NOW,
        )
    )


def _assert_normal_page(response) -> None:
    assert response.status_code == 200
    lowered = response.text.lower()
    for forbidden in (
        "<pre",
        "schema_version",
        "action_id",
        "traceback",
        SECRET_SNAPSHOT,
        "internal-content-hash",
    ):
        assert forbidden not in lowered


def test_operator_next_is_a_today_queue_with_one_clear_primary_action(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/operator-next")

    _assert_normal_page(response)
    assert "今日待办" in response.text
    assert "胜负彩 26116 期" in response.text
    assert "继续逐场裁决" in response.text
    assert response.text.count('data-primary-command="true"') == 1
    assert "/operator-next/zucai" in response.text
    assert "/operator-next/jczq" in response.text


def test_lane_page_separates_current_work_from_history(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/operator-next/zucai")

    _assert_normal_page(response)
    assert "胜负彩" in response.text
    assert "当前期次" in response.text
    assert "26116" in response.text
    assert "历史记录" in response.text
    assert "26115" in response.text


def test_task_and_work_item_pages_show_business_facts_without_internal_tokens(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, mode="active")

    task = client.get("/operator-next/zucai/26116")
    work_item = client.get("/operator-next/zucai/26116/sale-wave-opaque0001")

    for response in (task, work_item):
        _assert_normal_page(response)
        assert "水晶宫 vs 曼彻斯特城" in response.text
        assert "英格兰足总杯" in response.text
        assert "已完成 2 / 14 场" in response.text
        assert "补齐证据后裁决" in response.text
    assert "本期 14 场" in work_item.text
    assert "冻结本轮判断处方" in work_item.text
    assert 'data-action="freeze-judgment-prescription"' in work_item.text
    assert 'class="status-icon" aria-hidden="true"' in work_item.text
    assert 'href="/operator-next/audit/opaque-audit-token"' in work_item.text
    assert "技术审计" in work_item.text


def test_maintenance_page_is_diagnostic_only(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/operator-next/maintenance")

    _assert_normal_page(response)
    assert "运行与确认" in response.text
    assert "诊断暂不可用" in response.text
    assert "检查 OpenClaw 确认服务" in response.text
    assert "启用" not in response.text
    assert "停用" not in response.text
    assert "立即运行" not in response.text


def test_operator_javascript_uses_server_navigation_and_restores_focus() -> None:
    script = (
        Path(__file__).parents[3]
        / "nutmeg/interfaces/web/static/product/operator.js"
    ).read_text(encoding="utf-8")

    assert "result.navigation_href" in script
    assert "window.location.assign" in script
    assert "sessionStorage" in script
    assert "focus()" in script
    assert "window.location.reload()" not in script


def test_v2_confirmation_page_formats_minor_units_and_hides_signed_tokens(
    tmp_path: Path,
) -> None:
    response = _client(
        tmp_path,
        mode="active",
        operator_queries=_ConfirmationQueries("not_issued"),
    ).get("/operator-next/zucai/26116/sale-wave-opaque0001")

    _assert_normal_page(response)
    assert "¥1,728.00" in response.text
    assert RAW_ARTIFACT_ID not in response.text
    assert CONFIRM_COMMAND_TOKEN not in response.text
    assert ARTIFACT_TOKEN not in response.text
    assert 'data-action="request-confirmation"' in response.text
    assert 'data-task-key="zucai:26116"' in response.text


def test_v2_expired_confirmation_is_terminal_shadow_without_resend(
    tmp_path: Path,
) -> None:
    response = _client(
        tmp_path,
        mode="active",
        operator_queries=_ConfirmationQueries("expired"),
    ).get("/operator-next/zucai/26116/sale-wave-opaque0001")

    _assert_normal_page(response)
    assert "确认已过期" in response.text
    assert "按未出票处理" in response.text
    assert "重新发送" not in response.text
    assert 'data-action="request-confirmation"' not in response.text
    assert "发送 Telegram 本人确认" not in response.text


def test_confirmation_javascript_refreshes_v2_tokens_before_request() -> None:
    script = (
        Path(__file__).parents[3]
        / "nutmeg/interfaces/web/static/product/operator.js"
    ).read_text(encoding="utf-8")
    branch = script.split('if (action === "request-confirmation")', 1)[1].split(
        'if (action === "request-settlement")',
        1,
    )[0]

    assert "const step = await currentOperatorStep(form);" in branch
    assert 'postJson("/api/v2/operator"' in branch
    assert 'kind: "request_confirmation"' in branch
    assert "expected_snapshot_token: step.command_token" in branch
    assert "ticket_artifact_token: step.ticket_artifact_token" in branch


def test_task_detail_rejects_a_step_that_disagrees_with_the_active_phase() -> None:
    payload = _task_detail(_task("26116")).model_dump(mode="python")
    payload["work_items"][0]["phase"] = "compare_tickets"
    payload["active_work_item"]["phase"] = "compare_tickets"

    with pytest.raises(ValidationError, match="active phase"):
        OperatorTaskDetailV1.model_validate(payload)
