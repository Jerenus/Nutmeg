import hashlib
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


def test_command_center_match_link_url_encodes_and_preserves_cutoff(
    client: TestClient,
) -> None:
    response = client.get("/?date=2026-08-24")
    href = "/matches/match-1?as_of=2026-08-24T10%3A00%3A00%2B00%3A00"

    assert f'href="{href}"' in response.text
    detail = client.get(href)
    assert detail.status_code == 200
    assert "2026-08-24T10:00:00+00:00" in detail.text


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
    favicon = client.get("/assets/product/favicon.svg")

    assert 'class="skip-link" href="#main-content"' in response.text
    assert "<nav" in response.text
    assert "<main" in response.text
    assert "<aside" in response.text
    assert css.status_code == 200
    assert favicon.status_code == 200
    assert 'rel="icon" href="/assets/product/favicon.svg"' in response.text
    assert ":focus-visible" in css.text
    assert "--paper: #f5f7f3" in css.text
    assert not re.search(r'(?:src|href)="https?://', response.text)
    assert "<script>" not in response.text


def test_operations_page_shows_source_age_identity_and_failure(
    client: TestClient,
) -> None:
    response = client.get("/operations?as_of=2026-08-24T10:00:00Z")

    assert response.status_code == 200
    assert 'data-workspace="operations"' in response.text
    assert "sporttery" in response.text
    assert "team-duplicate" in response.text
    assert 'data-action="merge-identity"' in response.text
    assert "调度状态尚未接入本体事实" in response.text
    assert "直接编辑数据库" not in response.text


def test_merge_controls_embed_no_privileged_actor(client: TestClient) -> None:
    html = client.get("/operations").text
    script = client.get("/assets/product/app.js")

    assert 'name="actor_role"' not in html
    assert 'name="actor_id"' not in html
    assert 'aria-live="polite"' in html
    assert script.status_code == 200
    assert "/api/v1/session" in script.text
    assert "crypto.randomUUID()" in script.text
    assert "X-CSRF-Token" in script.text


def test_match_page_keeps_as_of_and_links_source_lineage(
    client: TestClient,
) -> None:
    response = client.get("/matches/match-1?as_of=2026-08-24T10:00:00Z")

    assert response.status_code == 200
    assert "2026-08-24T10:00:00+00:00" in response.text
    assert "legacy_unbundled" in response.text
    assert "/lineage/forecast_revision/fr-legacy" in response.text
    assert "obs-before" in response.text
    assert "obs-future" not in response.text


def test_lineage_page_renders_typed_edges_not_raw_sql(client: TestClient) -> None:
    response = client.get("/lineage/forecast_revision/fr-legacy")
    artifact_id = "sha256:" + hashlib.sha256(b"sporttery-fresh").hexdigest()
    artifact = client.get(f"/lineage/source_artifact/{artifact_id}")

    assert response.status_code == 200
    assert "forecast_for_match" in response.text
    assert "forecast_uses_snapshot" in response.text
    assert artifact.status_code == 200
    assert "created_by_action" in artifact.text
    assert "SELECT " not in response.text
    assert "SELECT " not in artifact.text


@pytest.mark.parametrize(
    "path",
    ["/matches/absent", "/lineage/forecast_revision/absent"],
)
def test_absent_ui_object_renders_stable_404(
    client: TestClient,
    path: str,
) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert "对象未找到" in response.text
    assert "Traceback" not in response.text
