from __future__ import annotations

import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageChops
from playwright.sync_api import Browser, Page, sync_playwright

from nutmeg.interfaces.operator_ui import mount_operator_ui
from nutmeg.product.operator_contracts import (
    CompleteStep,
    ConfirmationStep,
    LedgerStep,
    OperatorLane,
)
from tests.product.operator_v2.test_candidate_ui import _step as _candidate_step
from tests.product.operator_v2.test_judgment_ui import _step as _judgment_step
from tests.product.operator_v2.test_no_ticket_ui import _task as _deployment_task
from tests.product.operator_v2.test_operator_pages import (
    NOW,
    _client,
    _OperatorQueries,
    _slate,
)
from tests.product.operator_v2.test_result_ui import (
    _match as _result_match,
)
from tests.product.operator_v2.test_result_ui import (
    _source as _result_source,
)
from tests.product.operator_v2.test_result_ui import (
    _step as _result_step,
)
from tests.product.operator_v2.test_review_ui import _step as _review_step

INTERNAL_TEXT = re.compile(
    r"schema_version|action_id|content_hash|snapshot_token|traceback|[a-f0-9]{40,}",
    re.IGNORECASE,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _overlaps(left: dict[str, float], right: dict[str, float]) -> bool:
    return not (
        left["x"] + left["width"] <= right["x"]
        or right["x"] + right["width"] <= left["x"]
        or left["y"] + left["height"] <= right["y"]
        or right["y"] + right["height"] <= left["y"]
    )


@dataclass(frozen=True, slots=True)
class _BrowserScenario:
    business_key: str
    phase: str
    step: object
    expected_text: tuple[str, ...]
    expected_primary_count: int
    task_state: str = "current"

    @property
    def work_item_key(self) -> str:
        return f"work-{self.business_key}"

    @property
    def path(self) -> str:
        return f"/operator-next/zucai/{self.business_key}/{self.work_item_key}"


def _with_task_id(step, business_key: str):
    task_id = f"zucai:{business_key}"
    if hasattr(step, "model_copy"):
        return step.model_copy(update={"task_id": task_id})
    return SimpleNamespace(**(vars(step) | {"task_id": task_id}))


def _result_conflict_step():
    return _result_step(
        task_id="zucai:result-conflict",
        result_state="conflict",
        result_matches=[
            _result_match(
                agreement="conflict",
                disposition=None,
                home=None,
                away=None,
                sources=[
                    _result_source("API-Football", "available", "2 - 1"),
                    _result_source("官方竞彩", "available", "1 - 1"),
                    _result_source("人工核对", "available", "2 - 1"),
                ],
            )
        ],
        settlement_state="result_waiting",
        settlement_command_token=None,
        settlement_ready=False,
    )


_SCENARIOS = (
    _BrowserScenario(
        business_key="judgment",
        phase="judge_matches",
        step=_with_task_id(_judgment_step("match_judgment"), "judgment"),
        expected_text=("逐场判断", "水晶宫 - 曼彻斯特城", "提交本场并继续"),
        expected_primary_count=1,
    ),
    _BrowserScenario(
        business_key="candidate",
        phase="compare_tickets",
        step=_with_task_id(_candidate_step(), "candidate"),
        expected_text=("比较候选票", "U864-A", "确认选择并进入部署审计"),
        expected_primary_count=1,
    ),
    _BrowserScenario(
        business_key="audit-no-ticket",
        phase="audit_deployment",
        step=_with_task_id(
            _deployment_task(audit_state="pass", mode="create_ticket_batch").step,
            "audit-no-ticket",
        ),
        expected_text=("审计与部署", "创建受保护票据", "明确不出票"),
        expected_primary_count=1,
    ),
    _BrowserScenario(
        business_key="confirmation-open",
        phase="await_confirmation",
        step=ConfirmationStep(
            task_id="zucai:confirmation-open",
            ticket_artifact_id="artifact-confirmation-open",
            amount=200.0,
            currency="CNY",
            deadline_at=NOW + timedelta(hours=1),
            confirmation_state="open",
            confirmation_expires_at=NOW + timedelta(minutes=10),
        ),
        expected_text=("出票确认", "等待你在 Telegram 点击", "页面会自动检查确认状态"),
        expected_primary_count=0,
    ),
    _BrowserScenario(
        business_key="confirmation-timeout",
        phase="await_confirmation",
        step=ConfirmationStep(
            surface_version="2",
            task_id="zucai:confirmation-timeout",
            ticket_artifact_id=None,
            amount=None,
            amount_minor=20_000,
            currency="CNY",
            deadline_at=NOW - timedelta(minutes=1),
            confirmation_state="expired",
            confirmation_expires_at=NOW - timedelta(minutes=2),
            command_token=None,
            ticket_artifact_token=None,
        ),
        expected_text=("确认已过期", "按未出票处理", "本票没有入账"),
        expected_primary_count=0,
    ),
    _BrowserScenario(
        business_key="ledger",
        phase="blocked",
        step=LedgerStep(
            task_id="zucai:ledger",
            ticket_artifact_id="artifact-ledger",
            placement_state="unplaced",
            amount=200.0,
            currency="CNY",
            external_reference=None,
        ),
        expected_text=("等待入账记录", "页面会自动检查入账状态"),
        expected_primary_count=0,
    ),
    _BrowserScenario(
        business_key="result-conflict",
        phase="await_result",
        step=_result_conflict_step(),
        expected_text=("赛果与结算", "三源结果不一致", "结算会保持暂停"),
        expected_primary_count=0,
    ),
    _BrowserScenario(
        business_key="settlement",
        phase="await_result",
        step=_with_task_id(_result_step(settlement_ready=True), "settlement"),
        expected_text=("90 分钟赛果已核对", "开始结算"),
        expected_primary_count=1,
    ),
    _BrowserScenario(
        business_key="review",
        phase="review",
        step=_with_task_id(_review_step(), "review"),
        expected_text=("预测真值", "资金账", "干预质量"),
        expected_primary_count=1,
    ),
    _BrowserScenario(
        business_key="archive",
        phase="complete",
        step=CompleteStep(
            task_id="zucai:archive",
            title="历史期次已完成",
            summary="所有确定性记录已经归档。",
        ),
        expected_text=("已完成", "历史期次已完成"),
        expected_primary_count=0,
        task_state="archive",
    ),
)


def _scenario_detail(scenario: _BrowserScenario):
    work_item = SimpleNamespace(
        work_item_key=scenario.work_item_key,
        scope_kind="sale_wave",
        scope_label=f"{scenario.business_key} 工作项",
        phase=scenario.phase,
        deployment_outcome=None,
        next_deadline_at=NOW + timedelta(hours=1),
        is_current=scenario.task_state == "current",
        snapshot_token="opaque-browser-snapshot",
        progress=SimpleNamespace(progress_label="当前阶段"),
        blocking_reason=None,
        next_action=None,
        audit_href=None,
    )
    return SimpleNamespace(
        as_of=NOW,
        task_id=f"zucai:{scenario.business_key}",
        lane=OperatorLane.ZUCAI,
        business_key=scenario.business_key,
        task_label=f"胜负彩 {scenario.business_key}",
        task_state=scenario.task_state,
        current_slate=_slate(
            scenario.business_key,
            state="current" if scenario.task_state == "current" else "superseded",
        ),
        work_items=(work_item,),
        active_work_item=work_item,
        step=scenario.step,
        no_ticket=None,
    )


class _LifecycleQueries(_OperatorQueries):
    def __init__(self) -> None:
        super().__init__()
        self.details = {
            scenario.business_key: _scenario_detail(scenario)
            for scenario in _SCENARIOS
        }

    def task_v2(
        self,
        lane: OperatorLane,
        business_key: str,
        *,
        as_of,
    ):
        del as_of
        assert lane is OperatorLane.ZUCAI
        return self.details[business_key]

    def work_item_v2(
        self,
        lane: OperatorLane,
        business_key: str,
        work_item_key: str,
        *,
        as_of,
    ):
        detail = self.task_v2(lane, business_key, as_of=as_of)
        assert detail.active_work_item.work_item_key == work_item_key
        return detail

    def audit(self, token: str, *, as_of):
        assert token == "browser-audit-token"
        return SimpleNamespace(
            as_of=as_of,
            title="本期工作项技术记录",
            task_label="胜负彩 26116 期",
            work_item_label="本期 14 场",
            return_href="/operator-next/zucai/audit-no-ticket/work-audit-no-ticket",
            task_id="zucai:26116",
            work_item_id="work-item-browser-audit",
            task_snapshot_hash="a" * 64,
            lineage=(
                SimpleNamespace(
                    relation="uses",
                    object_type="official_sale_slate_revision",
                    object_id="slate-browser-audit",
                    revision_id="revision-browser-audit",
                    content_hash="b" * 64,
                    created_by_action_id="action-browser-audit",
                    source_payload_location="fixture://browser/audit",
                ),
            ),
            projection=SimpleNamespace(
                projection_name="scoreboard",
                state="ready",
                projection_version="scoreboard-v3",
                current_action_high_watermark=17,
                source_action_high_watermark=17,
                built_at=NOW,
            ),
        )


def _lifecycle_app() -> FastAPI:
    app = FastAPI()
    asset_root = (
        Path(__file__).resolve().parents[2]
        / "nutmeg"
        / "interfaces"
        / "web"
        / "static"
        / "product"
    )
    app.mount("/assets/product", StaticFiles(directory=asset_root), name="product-assets")
    mount_operator_ui(
        app,
        SimpleNamespace(operator_queries=_LifecycleQueries()),
        lambda: NOW,
        mount_root=False,
        mount_next=True,
        read_only=False,
    )
    return app


@pytest.fixture
def browser_page(tmp_path: Path, browser_runtime: Browser):
    application = _client(tmp_path).app
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        thread.join(0.01)
    assert server.started
    page = browser_runtime.new_page()
    try:
        yield page, f"http://127.0.0.1:{port}"
    finally:
        page.close()
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser_runtime():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def lifecycle_browser_page(browser_runtime: Browser):
    application = _lifecycle_app()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        thread.join(0.01)
    assert server.started
    page = browser_runtime.new_page()
    try:
        yield page, f"http://127.0.0.1:{port}"
    finally:
        page.close()
        server.should_exit = True
        thread.join(timeout=5)


def _assert_nonblank_screenshot(page: Page, path: Path) -> None:
    page.screenshot(path=str(path), full_page=True)
    assert path.stat().st_size > 5_000
    with Image.open(path).convert("RGB") as rendered:
        background = Image.new("RGB", rendered.size, rendered.getpixel((0, 0)))
        assert ImageChops.difference(rendered, background).getbbox() is not None


def _assert_key_controls_do_not_overlap(page: Page) -> None:
    controls = page.locator(
        ".current-step button:visible, .current-step summary:visible, "
        ".current-step a.primary-link:visible, .current-step a.secondary-link:visible"
    )
    boxes = [control.bounding_box() for control in controls.all()]
    assert all(box is not None for box in boxes)
    visible_boxes = [box for box in boxes if box is not None]
    for left, right in combinations(visible_boxes, 2):
        assert not _overlaps(left, right)


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda item: item.business_key)
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_full_lifecycle_work_item_surfaces_are_operable_at_both_viewports(
    lifecycle_browser_page: tuple[Page, str],
    tmp_path: Path,
    scenario: _BrowserScenario,
    width: int,
    height: int,
) -> None:
    page, base_url = lifecycle_browser_page
    page.set_viewport_size({"width": width, "height": height})

    response = page.goto(base_url + scenario.path, wait_until="networkidle")

    assert response is not None and response.status == 200
    assert page.url == base_url + scenario.path
    assert page.locator("#main-content").inner_text().strip()
    assert page.locator("pre").count() == 0
    assert page.locator(f"[data-step-kind='{scenario.step.kind}']").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    main_text = page.locator("#main-content").inner_text()
    assert all(text in main_text for text in scenario.expected_text)
    assert not INTERNAL_TEXT.search(main_text)

    header = page.locator(".workbench-header").bounding_box()
    main = page.locator("#main-content").bounding_box()
    assert header and main
    assert header["y"] + header["height"] <= main["y"]

    assert page.locator("[data-primary-command='true']:visible").count() <= 1
    _assert_key_controls_do_not_overlap(page)
    _assert_nonblank_screenshot(
        page,
        tmp_path / f"operator-{scenario.business_key}-{width}x{height}.png",
    )


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda item: item.business_key)
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_each_lifecycle_surface_has_at_most_one_contextual_primary_action(
    lifecycle_browser_page: tuple[Page, str],
    scenario: _BrowserScenario,
    width: int,
    height: int,
) -> None:
    page, base_url = lifecycle_browser_page
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + scenario.path, wait_until="networkidle")

    primary = page.locator(
        ".current-step .primary-action:visible, "
        ".current-step a.primary-link:visible"
    )

    assert primary.count() == scenario.expected_primary_count


def test_v2_confirmation_timeout_is_terminal_and_never_offers_resend(
    lifecycle_browser_page: tuple[Page, str],
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(
        item for item in _SCENARIOS if item.business_key == "confirmation-timeout"
    )
    page.goto(base_url + scenario.path, wait_until="networkidle")

    assert page.get_by_text("确认已过期，按未出票处理", exact=True).count() == 1
    assert page.get_by_text("确认窗口已经截止，本票没有入账。", exact=True).count() == 1
    assert page.get_by_role(
        "button",
        name="发送 Telegram 本人确认",
        exact=True,
    ).count() == 0
    assert page.locator('form[data-action="request-confirmation"]').count() == 0
    assert page.locator('form[data-action="request-telegram-confirmation"]').count() == 0


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_judgment_probability_values_fit_their_fields(
    lifecycle_browser_page: tuple[Page, str],
    width: int,
    height: int,
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(item for item in _SCENARIOS if item.business_key == "judgment")
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + scenario.path, wait_until="networkidle")

    overflowing = page.locator(
        ".probability-row > *, .probability-row input"
    ).evaluate_all(
        """nodes => nodes
          .filter(node => node.scrollWidth > node.clientWidth + 1)
          .map(node => ({
            field: node.textContent?.trim() || node.getAttribute('name'),
            value: node.value || null,
            clientWidth: node.clientWidth,
            scrollWidth: node.scrollWidth
          }))"""
    )

    assert overflowing == []


def test_mobile_candidate_comparison_exposes_every_column_without_clipping(
    lifecycle_browser_page: tuple[Page, str],
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(item for item in _SCENARIOS if item.business_key == "candidate")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url + scenario.path, wait_until="networkidle")

    table_widths = page.locator(".candidate-comparison table").evaluate_all(
        """tables => tables.map(table => ({
          table: table.scrollWidth,
          viewport: table.parentElement.clientWidth
        }))"""
    )

    assert table_widths
    assert all(item["table"] <= item["viewport"] + 1 for item in table_widths)


def test_desktop_candidate_comparison_uses_the_full_workbench_width(
    lifecycle_browser_page: tuple[Page, str],
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(item for item in _SCENARIOS if item.business_key == "candidate")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base_url + scenario.path, wait_until="networkidle")

    tables = page.locator(".candidate-comparison table")
    assert tables.count() == 2
    table = tables.nth(0).bounding_box()

    assert table is not None
    assert table["width"] >= 1_000


def test_desktop_candidate_metric_values_use_at_most_two_lines(
    lifecycle_browser_page: tuple[Page, str],
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(item for item in _SCENARIOS if item.business_key == "candidate")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base_url + scenario.path, wait_until="networkidle")

    overly_tall_values = page.locator(
        ".candidate-table .candidate-metrics dd"
    ).evaluate_all(
        """nodes => nodes
          .map(node => {
            const style = getComputedStyle(node);
            const lineHeight = parseFloat(style.lineHeight)
              || parseFloat(style.fontSize) * 1.3;
            return {
              value: node.textContent?.trim(),
              height: node.getBoundingClientRect().height,
              maxHeight: lineHeight * 2 + 1
            };
          })
          .filter(item => item.height > item.maxHeight)"""
    )

    assert overly_tall_values == []


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_review_text_controls_have_stable_operable_dimensions(
    lifecycle_browser_page: tuple[Page, str],
    width: int,
    height: int,
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(item for item in _SCENARIOS if item.business_key == "review")
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + scenario.path, wait_until="networkidle")
    controls = page.locator(
        ".current-step .operator-form "
        "input:not([type='radio']):not([type='checkbox']), "
        ".current-step .operator-form select, "
        ".current-step .operator-form textarea"
    )

    boxes = [control.bounding_box() for control in controls.all()]

    assert boxes
    assert all(box is not None for box in boxes)
    assert all(box["height"] >= 40 for box in boxes if box is not None)
    assert all(box["width"] >= 120 for box in boxes if box is not None)


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_technical_audit_surface_is_readable_without_raw_json(
    lifecycle_browser_page: tuple[Page, str],
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    page, base_url = lifecycle_browser_page
    page.set_viewport_size({"width": width, "height": height})
    path = "/operator-next/audit/browser-audit-token"

    response = page.goto(base_url + path, wait_until="networkidle")

    assert response is not None and response.status == 200
    assert page.get_by_role("heading", name="技术审计", exact=True).count() == 1
    assert page.get_by_role("heading", name="技术血缘", exact=True).count() == 1
    assert page.get_by_role("heading", name="投影水位", exact=True).count() == 1
    assert page.locator("pre").count() == 0
    assert page.locator("[data-primary-command='true']:visible").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    _assert_nonblank_screenshot(
        page,
        tmp_path / f"operator-audit-{width}x{height}.png",
    )


def test_command_navigation_restores_focus_to_the_single_primary_action(
    lifecycle_browser_page: tuple[Page, str],
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(
        item for item in _SCENARIOS if item.business_key == "audit-no-ticket"
    )
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base_url + scenario.path, wait_until="networkidle")
    assert page.locator("form[data-primary-command='true'] button").count() == 1

    page.evaluate(
        "sessionStorage.setItem('nutmeg.operator.focus-after-command', 'true')"
    )
    page.reload(wait_until="networkidle")

    focus_state = page.evaluate(
        "({"
        "stored: sessionStorage.getItem('nutmeg.operator.focus-after-command'),"
        "activeTag: document.activeElement?.tagName || null,"
        "activeText: document.activeElement?.textContent?.trim() || null,"
        "matches: document.activeElement === "
        "document.querySelector(\"form[data-primary-command='true'] button\")"
        "})"
    )
    assert focus_state["stored"] is None, focus_state
    assert focus_state["matches"], focus_state


def test_candidate_choice_starts_empty_and_keeps_the_advance_action_visible(
    lifecycle_browser_page: tuple[Page, str],
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(item for item in _SCENARIOS if item.business_key == "candidate")
    page.goto(base_url + scenario.path, wait_until="networkidle")
    choices = page.locator('input[name="candidate_token"]')

    assert choices.count() > 0
    assert page.locator('input[name="candidate_token"]:checked').count() == 0

    choices.nth(0).check()

    assert page.locator('input[name="candidate_token"]:checked').count() == 1
    assert page.get_by_role(
        "button",
        name="确认选择并进入部署审计",
        exact=True,
    ).is_visible()


def test_explicit_no_ticket_expands_into_a_complete_secondary_form(
    lifecycle_browser_page: tuple[Page, str],
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(
        item for item in _SCENARIOS if item.business_key == "audit-no-ticket"
    )
    page.goto(base_url + scenario.path, wait_until="networkidle")
    toggle = page.get_by_text("明确不出票", exact=True)
    assert toggle.count() == 1

    toggle.click()
    page.locator('select[name="reason_code"]').select_option("operator_discretion")
    page.locator(
        'input[name="reason_basis"][value="operator_judgment"]'
    ).check()
    page.locator('textarea[name="reason_text"]').fill("由 Jun 明确记录的测试理由。")

    assert page.get_by_role(
        "button",
        name="记录本次不出票",
        exact=True,
    ).is_visible()
    assert page.get_by_role(
        "button",
        name="创建受保护票据",
        exact=True,
    ).is_visible()


def test_v2_deployment_refresh_stays_on_the_current_work_item_route(
    lifecycle_browser_page: tuple[Page, str],
) -> None:
    page, base_url = lifecycle_browser_page
    scenario = next(
        item for item in _SCENARIOS if item.business_key == "audit-no-ticket"
    )
    page.goto(base_url + scenario.path, wait_until="networkidle")

    assert page.get_by_role(
        "link",
        name="刷新当前任务",
        exact=True,
    ).get_attribute("href") == scenario.path


def test_real_browser_posts_advance_one_jczq_work_item_to_confirmation(
    tmp_path: Path,
    browser_runtime: Browser,
) -> None:
    from nutmeg.interfaces.product_api import create_product_app
    from nutmeg.ontology.actions.protected_ticket_actions import ProtectedTicketActions
    from nutmeg.ontology.actions.workflow_actions import WorkflowActions
    from nutmeg.ontology.artifacts import ContentAddressedArtifactStore
    from nutmeg.ontology.operator.result_actions import OperatorResultActions
    from nutmeg.ontology.repository.finance import CashAccountRow
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from nutmeg.product.actions import ProductActionGateway
    from nutmeg.product.operator_actions import OperatorActionService
    from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
    from nutmeg.product.operator_workers import (
        CandidateGenerationWorker,
        OperatorInfrastructureWorkers,
        audit_current_candidate,
    )
    from tests.ontology.operator.test_judgment_actions import (
        _baseline_request,
        _fixture,
    )
    from tests.product.operator_v2.test_judgment_api import (
        KEY,
        _seed_task_identity,
        _task_queries,
    )
    from tests.product.operator_v2.test_judgment_api import (
        NOW as JUDGMENT_NOW,
    )
    from tests.product.test_operator_v2_e2e import FIXTURE_ROOT, _runtime

    fixture = _fixture(tmp_path / "real-browser-chain")
    _seed_task_identity(fixture)
    fixture.decision_actions.freeze_market_prior_baseline(_baseline_request(fixture))
    with OntologyUnitOfWork(fixture.engine) as uow:
        uow.finance.ensure_account(CashAccountRow("acct-jczq", "jczq", "CNY", "active"))

    queries = _task_queries(fixture)
    protected = ProtectedTicketActions(
        fixture.action_service,
        ContentAddressedArtifactStore(tmp_path / "real-browser-chain-artifacts"),
        operator_decisions=fixture.decision_actions,
        operator_candidate_auditor=audit_current_candidate,
    )
    actions = OperatorActionService(
        queries=queries,
        action_gateway=ProductActionGateway(
            type(
                "Kernel",
                (),
                {"workflow": WorkflowActions(fixture.action_service)},
            )(),
            object(),
            clock=lambda: JUDGMENT_NOW,
        ),
        decision_actions=fixture.decision_actions,
        protected_tickets=protected,
        snapshot_tokens=OperatorSnapshotTokenCodec(KEY),
        clock=lambda: JUDGMENT_NOW,
    )
    data_dir = tmp_path / "real-browser-chain-runtime"
    data_dir.mkdir(parents=True)
    scoreboard_bytes = (FIXTURE_ROOT / "scoreboard.json").read_bytes()
    scoreboard_path = data_dir / "scoreboard.json"
    scoreboard_path.write_bytes(scoreboard_bytes)
    workers = OperatorInfrastructureWorkers(
        data_dir=data_dir,
        clock=lambda: JUDGMENT_NOW,
        poll_interval_seconds=0.01,
        candidate_generation=CandidateGenerationWorker(
            action_service=fixture.action_service,
            result_actions=OperatorResultActions(fixture.action_service),
            worker_id="operator-browser-candidate-generation",
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
    application = create_product_app(
        services,
        session_secret="real-browser-lifecycle-session",
        csrf_secret="real-browser-lifecycle-csrf",
        clock=lambda: JUDGMENT_NOW,
        runtime_config=runtime,
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        thread.join(0.01)
    assert server.started

    page = browser_runtime.new_page()
    base_url = f"http://127.0.0.1:{port}"
    posted_kinds: list[str] = []

    def remember_operator_post(request) -> None:
        if request.method == "POST" and request.url == base_url + "/api/v2/operator":
            posted_kinds.append(request.post_data_json["kind"])

    def submit_and_wait(button_name: str, next_text: str) -> None:
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url == base_url + "/api/v2/operator"
        ) as response_info:
            page.get_by_role("button", name=button_name, exact=True).click()
        assert response_info.value.status in {200, 202}, response_info.value.text()
        try:
            page.get_by_text(next_text, exact=False).first.wait_for(timeout=5_000)
        except Exception as error:
            raise AssertionError(
                f"browser did not advance to {next_text!r}; url={page.url!r}; "
                f"body={page.locator('body').inner_text()!r}"
            ) from error

    page.on("request", remember_operator_post)
    try:
        task = queries.task_v2(
            OperatorLane.JCZQ,
            "2026-09-04",
            as_of=JUDGMENT_NOW,
        )
        work_item_path = (
            "/operator-next/jczq/2026-09-04/"
            f"{task.active_work_item.work_item_key}"
        )
        response = page.goto(base_url + work_item_path, wait_until="networkidle")
        assert response is not None and response.status == 200
        assert page.get_by_role(
            "heading",
            name="限定本轮票面搜索范围",
            exact=True,
        ).count() == 1

        page.locator('input[name="allowed_face_bundle"]').nth(0).check()
        page.locator('input[name="allowed_face_bundle"]').nth(1).check()
        page.locator('input[name="structure_code"]').check()
        submit_and_wait("保存范围并开始逐场判断", "逐场判断")

        page.locator('input[name="face_bundle"]').nth(0).check()
        page.locator('input[name="rule_id"]').nth(0).check()
        # 锚方完整度没有默认值：不选它，表单根本不会提交。
        page.locator('input[name="anchor_integrity"][value="pass"]').check()
        page.locator('[data-precedent-row]').last.locator(
            'input[name="precedent_ref"]'
        ).fill("2026-05-12 同场地同型 1:0 主胜")
        page.locator('[data-precedent-row]').last.locator(
            'select[name="precedent_status"]'
        ).select_option("dead")
        page.locator('textarea[name="falsifier"]').fill("阵容证据不再支持已登记结构。")
        page.locator('textarea[name="rationale"]').fill("Jun 依据冻结证据登记测试判断。")
        submit_and_wait("提交本场并继续", "冻结本轮判断处方")
        submit_and_wait("冻结处方并比较票面", "生成完整候选集")

        submit_and_wait("生成完整候选集", "生成完整候选集")
        comparison_deadline = time.monotonic() + 5
        while (
            page.get_by_role("heading", name="比较候选票", exact=True).count() == 0
            and time.monotonic() < comparison_deadline
        ):
            page.reload(wait_until="networkidle")
        assert page.get_by_role("heading", name="比较候选票", exact=True).count() == 1

        page.locator('input[name="candidate_token"]').nth(0).check()
        page.locator('textarea[name="reason"]').fill("Jun 选择该确定性候选进入部署审计。")
        submit_and_wait("确认选择并进入部署审计", "创建受保护票据")
        submit_and_wait("创建受保护票据", "审计与部署")

        if page.get_by_role("button", name="记录 WARN 裁决", exact=True).count():
            for finding in page.locator('input[name="finding_token"]').all():
                finding.check()
            for reason in page.locator("[data-warn-reason]").all():
                reason.fill("Jun 接受已披露的确定性 WARN。")
            submit_and_wait("记录 WARN 裁决", "审批受保护票据")
        submit_and_wait("审批受保护票据", "发送 Telegram 本人确认")

        expected_kinds = [
            "record_baseline_envelope",
            "commit_match_judgment",
            "freeze_judgment_prescription",
            "request_candidate_generation",
            "select_candidate",
            "create_ticket_batch",
            "approve_ticket_batch",
        ]
        if "adjudicate_audit_warn" in posted_kinds:
            expected_kinds.insert(-1, "adjudicate_audit_warn")
        assert posted_kinds == expected_kinds
        current = queries.task_v2(
            OperatorLane.JCZQ,
            "2026-09-04",
            as_of=JUDGMENT_NOW,
        )
        assert page.url == (
            base_url
            + "/operator-next/jczq/2026-09-04/"
            + current.active_work_item.work_item_key
        )
        assert page.get_by_role(
            "button",
            name="发送 Telegram 本人确认",
            exact=True,
        ).count() == 1
        assert page.locator("pre").count() == 0
        assert not INTERNAL_TEXT.search(page.locator("#main-content").inner_text())
        with fixture.engine.connect() as connection:
            domain_counts = tuple(
                int(
                    connection.exec_driver_sql(
                        f"SELECT COUNT(*) FROM {table_name}"
                    ).scalar_one()
                )
                for table_name in (
                    "operator_baseline_envelope_revisions",
                    "operator_match_judgment_revisions",
                    "operator_judgment_prescription_revisions",
                    "operator_candidate_generation_requests",
                    "operator_candidate_set_revisions",
                    "operator_candidate_selections",
                    "ticket_batch_revisions",
                    "audited_ticket_artifacts",
                )
            )
            committed_roles = connection.exec_driver_sql(
                "SELECT action_type, actor_role FROM actions WHERE status = 'committed'"
            ).all()
        assert domain_counts == (1, 1, 1, 1, 2, 1, 2, 1)
        assert ("commit_operator_match_judgment", "judge_operator") in committed_roles
        assert ("generate_ticket_candidate_set", "deterministic_system") in committed_roles
        assert not any(role == "ai_analyst" for _action_type, role in committed_roles)
        assert not any(
            action_type == "confirm_dispatch"
            for action_type, _role in committed_roles
        )
        assert scoreboard_path.read_bytes() == scoreboard_bytes
    finally:
        page.close()
        server.should_exit = True
        thread.join(timeout=5)


def test_real_browser_posts_zucai_settlement_and_lifespan_advances_to_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    browser_runtime: Browser,
) -> None:
    from nutmeg.interfaces.product_api import create_product_app
    from tests.ontology.operator import test_task_settlement as settlement_replay
    from tests.product.test_operator_v2_e2e import FIXTURE_ROOT, _sha256

    monkeypatch.delenv("NUTMEG_P10_REPLAY_ROOT", raising=False)
    monkeypatch.delenv("NUTMEG_PRODUCTION_DATA_DIR", raising=False)
    monkeypatch.delenv("NUTMEG_OPERATOR_TOKEN_SIGNING_KEY", raising=False)
    root, workspace = settlement_replay._public_replay_workspace(
        tmp_path / "real-browser-zucai"
    )
    captured_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
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
        manifest_name="zucai-browser-result.json",
        document=result_document,
    )
    assert receipt["outcome_count"] == 14

    scoreboard = root / "data" / "scoreboard.json"
    scoreboard.write_bytes((FIXTURE_ROOT / "scoreboard.json").read_bytes())
    scoreboard_checksum = _sha256(scoreboard)
    clock_at = datetime.now(UTC) + timedelta(minutes=5)
    services, runtime = settlement_replay._public_replay_services(
        root,
        clock_at=clock_at,
    )
    application = create_product_app(
        services,
        session_secret="real-browser-zucai-settlement-session",
        csrf_secret="real-browser-zucai-settlement-csrf",
        clock=lambda: clock_at,
        runtime_config=runtime,
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        thread.join(0.01)
    assert server.started

    page = browser_runtime.new_page()
    base_url = f"http://127.0.0.1:{port}"
    posted_payloads: list[dict[str, object]] = []

    def remember_operator_post(request) -> None:
        if request.method == "POST" and request.url == base_url + "/api/v2/operator":
            posted_payloads.append(request.post_data_json)

    page.on("request", remember_operator_post)
    try:
        task = services.operator_queries.task_v2(
            OperatorLane.ZUCAI,
            "26111",
            as_of=clock_at,
        )
        assert task.active_work_item.next_action.action_code == "request_settlement"
        work_item_path = (
            "/operator-next/zucai/26111/"
            f"{task.active_work_item.work_item_key}"
        )
        response = page.goto(
            base_url + work_item_path,
            wait_until="networkidle",
        )
        assert response is not None and response.status == 200
        assert page.get_by_role(
            "heading",
            name="赛果与结算",
            exact=True,
        ).count() == 1, page.locator("body").inner_text()
        assert page.get_by_role("button", name="开始结算", exact=True).count() == 1

        with page.expect_navigation(wait_until="domcontentloaded", timeout=10_000):
            with page.expect_response(
                lambda result: result.request.method == "POST"
                and result.url == base_url + "/api/v2/operator",
                timeout=10_000,
            ) as response_info:
                page.get_by_role("button", name="开始结算", exact=True).click()
        assert response_info.value.status == 202, response_info.value.text()
        assert len(posted_payloads) == 1
        assert posted_payloads[0]["schema_version"] == "2"
        assert posted_payloads[0]["kind"] == "request_settlement"
        assert posted_payloads[0]["task_key"] == "zucai:26111"
        assert posted_payloads[0]["expected_snapshot_token"]

        review_deadline = time.monotonic() + 10
        while time.monotonic() < review_deadline:
            page.goto(
                base_url + "/operator-next/zucai/26111",
                wait_until="domcontentloaded",
            )
            review_link = page.get_by_role("link", name="继续复盘", exact=True)
            if review_link.count():
                review_link.click()
                page.get_by_role(
                    "heading",
                    name="本期复盘",
                    exact=True,
                ).wait_for(timeout=10_000)
                break
            page.wait_for_timeout(250)
        else:
            worker_task = services.infrastructure_workers._task
            worker_error = (
                repr(worker_task.exception())
                if worker_task is not None and worker_task.done()
                else None
            )
            with engine.connect() as connection:
                worker_jobs = connection.exec_driver_sql(
                    "SELECT job_kind, state, attempt_count, last_error_code "
                    "FROM operator_worker_jobs ORDER BY rowid"
                ).all()
            pytest.fail(
                "zucai settlement did not advance to review; "
                f"worker_error={worker_error!r}; jobs={worker_jobs!r}; "
                f"url={page.url!r}; body={page.locator('body').inner_text()!r}"
            )

        assert page.locator("pre").count() == 0
        assert not INTERNAL_TEXT.search(page.locator("#main-content").inner_text())
        assert _sha256(scoreboard) == scoreboard_checksum
    finally:
        page.close()
        server.should_exit = True
        thread.join(timeout=10)


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_today_is_nonblank_private_and_overlap_free(
    browser_page: tuple[Page, str],
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    page, base_url = browser_page
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + "/operator-next", wait_until="networkidle")

    assert page.locator("[data-testid='today-queue']").count() == 1
    assert page.locator("pre").count() == 0
    assert page.locator("[data-primary-command='true']:visible").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not INTERNAL_TEXT.search(page.locator("body").inner_text())

    header = page.locator(".workbench-header").bounding_box()
    main = page.locator("#main-content").bounding_box()
    heading = page.locator(".queue-entry.is-primary h2").bounding_box()
    action = page.locator(".queue-entry.is-primary [data-primary-command]").bounding_box()
    assert header and main and heading and action
    assert header["y"] + header["height"] <= main["y"]
    assert not _overlaps(heading, action)

    screenshot = tmp_path / f"operator-next-{width}x{height}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    assert screenshot.stat().st_size > 5_000
    with Image.open(screenshot).convert("RGB") as rendered:
        background = Image.new("RGB", rendered.size, rendered.getpixel((0, 0)))
        assert ImageChops.difference(rendered, background).getbbox() is not None


def test_today_navigation_reaches_the_lane_without_json_surface(
    browser_page: tuple[Page, str],
) -> None:
    page, base_url = browser_page
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(base_url + "/operator-next", wait_until="networkidle")

    page.get_by_role("link", name="胜负彩", exact=True).click()
    page.wait_for_url(base_url + "/operator-next/zucai")

    assert page.get_by_role("heading", name="当前期次", exact=True).count() == 1
    assert page.get_by_text("胜负彩 26116 期", exact=True).count() == 1
    assert page.locator("pre").count() == 0
    assert not INTERNAL_TEXT.search(page.locator("body").inner_text())
