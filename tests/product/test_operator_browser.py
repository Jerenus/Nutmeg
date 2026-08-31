import re
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from playwright.sync_api import Page, sync_playwright

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.contracts import ProductActionResponse
from nutmeg.product.operator_contracts import OperatorTaskState
from tests.product.test_operator_ui import NOW, FakeOperatorQueries


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _BrowserOperatorActions:
    def __init__(self, queries: FakeOperatorQueries) -> None:
        self.queries = queries

    def resolve_issue_adjudication(self, task_id, command, **identity):
        self.queries.summary = self.queries.summary.model_copy(
            update={
                "state": OperatorTaskState.CONSTRUCT_TICKET,
                "next_action_label": "比较候选票",
            }
        )
        return ProductActionResponse(
            action_id="action-browser-adjudication",
            action_type="record_adjudication",
            status="committed",
            committed_at=NOW.isoformat(),
        )


@pytest.fixture
def operator_app(m2_product_services):
    operator_queries = FakeOperatorQueries()
    services = SimpleNamespace(
        kernel=m2_product_services.kernel,
        queries=m2_product_services.queries,
        actions=m2_product_services.actions,
        settings=m2_product_services.settings,
        copilot=None,
        tickets=SimpleNamespace(),
        operator_queries=operator_queries,
        operator_actions=_BrowserOperatorActions(operator_queries),
    )
    return create_product_app(
        services,
        session_secret="operator-browser-session",
        csrf_secret="operator-browser-csrf",
        clock=lambda: NOW,
    )


@pytest.fixture
def browser_page(operator_app):
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            operator_app,
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
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            yield page, f"http://127.0.0.1:{port}"
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_current_task_has_no_overlap_or_horizontal_escape(
    browser_page: tuple[Page, str],
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    page, base_url = browser_page
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + "/", wait_until="networkidle")

    assert page.locator("[data-workspace='operator-task']").count() == 1
    assert page.locator(".primary-action").count() == 1
    assert page.locator("pre").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    header = page.locator(".operator-header").bounding_box()
    main = page.locator("#main-content").bounding_box()
    evidence = page.locator(".evidence-list").bounding_box()
    form = page.locator(".operator-form").bounding_box()
    button = page.locator(".primary-action").bounding_box()
    assert header and main and header["y"] + header["height"] <= main["y"]
    assert evidence and form and evidence["y"] <= form["y"]
    assert button and button["height"] >= 44
    assert button["x"] >= 0 and button["x"] + button["width"] <= width
    assert page.locator("h1").evaluate(
        "node => parseFloat(getComputedStyle(node).fontSize)"
    ) <= 36
    body_text = page.locator("body").inner_text()
    assert not re.search(
        r"schema|outbox|action_id|content_hash|forecast_revision_id",
        body_text,
        re.I,
    )
    screenshot = tmp_path / f"operator-{width}x{height}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    assert screenshot.stat().st_size > 5_000


def test_keyboard_and_mutation_progress(browser_page: tuple[Page, str]) -> None:
    page, base_url = browser_page
    page.goto(base_url + "/", wait_until="networkidle")

    page.keyboard.press("Tab")
    assert page.locator(":focus").get_attribute("href") == "#main-content"
    options = page.locator("input[name='selected_option']")
    assert options.count() == 2
    options.first.check()
    page.locator("textarea[name='reason']").fill("browser fixture judgment")
    page.locator("button.primary-action").click()
    page.wait_for_selector("[data-step-kind='construct_ticket']")

    assert page.locator("[data-step-kind='construct_ticket']").count() == 1
    assert page.locator("pre").count() == 0
