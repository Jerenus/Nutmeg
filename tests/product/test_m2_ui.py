import re

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app

from .conftest import CLOCK


@pytest.fixture
def client(m2_product_services) -> TestClient:
    return TestClient(
        create_product_app(
            m2_product_services,
            session_secret="m2-ui-session-secret",
            csrf_secret="m2-ui-csrf-secret",
            clock=lambda: CLOCK,
        )
    )


def test_command_center_renders_semantic_attention_surface(
    client: TestClient,
) -> None:
    response = client.get("/?date=2026-08-24")

    assert response.status_code == 200
    assert 'lang="zh-CN"' in response.text
    assert 'data-workspace="command-center"' in response.text
    assert "Home FC" in response.text
    assert "ready" in response.text
    assert "最佳投注" not in response.text
    assert 'href="/matches/match-1' in response.text


def test_empty_filter_is_designed_state(client: TestClient) -> None:
    response = client.get("/?date=2026-08-24&q=absent")

    assert response.status_code == 200
    assert 'data-empty-state="board"' in response.text
    assert "没有符合当前筛选的比赛" in response.text


def test_shell_has_local_assets_landmarks_and_keyboard_focus(
    client: TestClient,
) -> None:
    response = client.get("/?date=2026-08-24")
    css = client.get("/assets/product/app.css")

    assert 'class="skip-link" href="#main-content"' in response.text
    assert "<nav" in response.text
    assert "<main" in response.text
    assert "<aside" in response.text
    assert css.status_code == 200
    assert ":focus-visible" in css.text
    assert "--paper: #f5f7f3" in css.text
    assert not re.search(r'(?:src|href)="https?://', response.text)
    assert "<script>" not in response.text
