import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app

from .conftest import CLOCK


@pytest.fixture
def client(m2_product_services) -> TestClient:
    return TestClient(
        create_product_app(
            m2_product_services,
            session_secret="m2-e2e-session-secret",
            csrf_secret="m2-e2e-csrf-secret",
            clock=lambda: CLOCK,
        )
    )


def _session(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/session")
    assert response.status_code == 200
    return {
        "X-CSRF-Token": response.json()["csrf_token"],
        "Origin": "http://testserver",
    }


def _merge_action_payload() -> dict[str, object]:
    return {
        "action_type": "merge_entity",
        "idempotency_key": "e2e:merge:1",
        "payload": {
            "entity_type": "team",
            "from_id": "team-duplicate",
            "into_id": "team-home",
            "reason": "same provider-backed club",
        },
        "expected_versions": {},
    }


def test_m2_golden_path_board_to_lineage_to_identity_merge(
    client: TestClient,
) -> None:
    command = client.get("/?date=2026-08-24")
    match = client.get("/matches/match-1?as_of=2026-08-24T10:00:00Z")
    lineage = client.get("/lineage/forecast_revision/fr-legacy")
    merged = client.post(
        "/api/v1/actions",
        headers=_session(client),
        json=_merge_action_payload(),
    )
    refreshed = client.get("/operations?as_of=2026-08-24T10:00:00Z")

    assert command.status_code == 200 and "Home FC" in command.text
    assert match.status_code == 200 and "obs-future" not in match.text
    assert lineage.status_code == 200 and "forecast_for_match" in lineage.text
    assert merged.status_code == 200 and merged.json()["status"] == "committed"
    assert 'data-identity-id="team-duplicate"' not in refreshed.text


def test_product_ui_has_durable_event_and_narrow_screen_contract(
    client: TestClient,
) -> None:
    html = client.get("/?date=2026-08-24").text
    script = client.get("/assets/product/app.js").text
    css = client.get("/assets/product/app.css").text

    assert 'data-event-state="idle"' in html
    assert "new EventSource" in script
    assert "sessionStorage" in script
    assert "事件流已连接" in script
    assert "事件流离线" in script
    assert "@media (max-width: 430px)" in css
    assert "min-height: 44px" in css
    assert "overflow-x: clip" in css


def test_narrow_screen_stacks_hero_ledger_before_operations_timestamp(
    client: TestClient,
) -> None:
    css = client.get("/assets/product/app.css").text
    narrow_rules = css.split("@media (max-width: 760px)", maxsplit=1)[1]

    assert re.search(
        r"\.hero-ledger\s*\{[^}]*grid-template-columns:\s*1fr;",
        narrow_rules,
        re.DOTALL,
    )


def test_formal_ui_contains_no_legacy_store_or_domain_arithmetic() -> None:
    paths = [
        Path("nutmeg/interfaces/product_api.py"),
        Path("nutmeg/interfaces/product_ui.py"),
        *Path("nutmeg/interfaces/web/templates/product").glob("*.html"),
        *Path("nutmeg/interfaces/web/static/product").glob("*.*"),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for forbidden in (
        "DecisionStore",
        "workbench.jsonl",
        "decisions.jsonl",
        'name="actor_role"',
        'name="actor_id"',
        "stake * odds",
        "payout =",
        "SELECT ",
    ):
        assert forbidden not in text
