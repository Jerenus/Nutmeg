import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app

from .conftest import CLOCK


@pytest.fixture
def client(m3_product_services) -> TestClient:
    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=m3_product_services.queries,
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=object(),
    )
    return TestClient(
        create_product_app(
            services,
            session_secret="m3-ui-session-secret",
            csrf_secret="m3-ui-csrf-secret",
            clock=lambda: CLOCK,
        )
    )


def test_match_room_exposes_temporal_evidence_conflicts_and_actions(
    client: TestClient,
) -> None:
    response = client.get(
        "/matches/match-1?as_of=2026-08-24T10:00:00Z"
    )

    assert response.status_code == 200
    html = response.text
    assert 'data-workspace="match-investigation"' in html
    assert 'data-investigation-cutoff="2026-08-24T10:00:00+00:00"' in html
    assert 'data-copilot-state="available"' in html
    assert "证据冲突" in html
    assert "来源片段" in html
    assert "市场时间线" in html
    assert 'data-action="copilot-investigate"' in html
    assert 'data-action="claim-adjudication"' in html
    assert 'data-action="proposal-resolution"' in html
    assert 'data-action="forecast-commit"' in html
    assert "obs-before" in html
    assert "obs-future" not in html
    assert "snapshot-future" not in html


def test_match_room_renders_workflow_objects_bundles_and_cited_proposals(
    client: TestClient,
) -> None:
    html = client.get(
        "/matches/match-1?as_of=2026-08-24T10:00:00Z"
    ).text

    assert "Canonical Context" in html
    assert "mr-before" in html
    assert "Flags / Predictions / Precedents" in html
    assert "flag-fixture" in html
    assert "prediction-fixture" in html
    assert "precedent-fixture" in html
    assert "EvidenceBundle" in html
    assert "bundle-fixture" in html
    assert "fixture-bundle-hash" in html
    assert "AgentProposal Thread" in html
    assert "fixture-agent" in html
    assert "Check the lineup evidence." in html
    assert "obs-before" in html
    assert "Citation coverage" in html


def test_investigation_mutations_keep_authority_and_arithmetic_server_side(
    client: TestClient,
) -> None:
    html = client.get("/matches/match-1").text
    script = client.get("/assets/product/app.js").text

    assert 'name="actor_role"' not in html
    assert 'name="actor_id"' not in html
    assert "portkey_api_key" not in html + script
    assert "async function postJson" in script
    assert "/api/v1/matches/${matchId}/copilot" in script
    assert 'action_type: values.get("claim_action")' in script
    assert 'action_type: "resolve_agent_proposal"' in script
    assert 'action_type: "commit_forecast"' in script
    assert "crypto.randomUUID()" in script
    assert "aria-live=\"polite\"" in html
    for forbidden in (
        "reduce((sum",
        "beliefTotal",
        "stake * odds",
        "payout =",
    ):
        assert forbidden not in script


def test_investigation_styles_define_three_column_desk_and_narrow_stack(
    client: TestClient,
) -> None:
    css = client.get("/assets/product/app.css").text

    assert re.search(
        r"\.decision-desk\s*\{[^}]*grid-template-columns:\s*repeat\(3,",
        css,
        re.DOTALL,
    )
    assert ".market-timeline li::before" in css
    assert ".source-spans" in css
    assert ".conflict-list" in css
    assert "textarea:focus-visible" in css
    narrow = css.split("@media (max-width: 760px)", maxsplit=1)[1]
    assert re.search(
        r"\.decision-desk[^\{]*\{[^}]*grid-template-columns:\s*1fr;",
        narrow,
        re.DOTALL,
    )
    assert "min-height: 44px" in narrow
    assert "overflow-wrap: anywhere" in css


def test_match_room_captures_adjudication_and_optional_proposal_binding(
    client: TestClient,
) -> None:
    html = client.get("/matches/match-1").text
    script = client.get("/assets/product/app.js").text

    assert 'data-action="record-adjudication"' in html
    assert 'name="reason"' in html
    assert 'name="evidence_rejected"' in html
    assert 'name="agent_proposal_id"' in html
    assert 'data-version="' in html
    assert 'action_type: "record_adjudication"' in script
    assert "agent_proposal_id: proposalId" in script
    assert "agent_proposal:${proposalId}" in script


def test_disabled_copilot_keeps_deterministic_investigation_usable(
    m3_product_services,
) -> None:
    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=m3_product_services.queries,
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=None,
    )
    disabled_client = TestClient(
        create_product_app(
            services,
            session_secret="m3-ui-disabled-session-secret",
            csrf_secret="m3-ui-disabled-csrf-secret",
            clock=lambda: CLOCK,
        )
    )

    html = disabled_client.get("/matches/match-1").text

    assert 'data-copilot-state="unavailable"' in html
    copilot_form = html.split('data-action="copilot-investigate"', 1)[1].split(
        "</form>", 1
    )[0]
    assert "disabled" in copilot_form
    assert '<button type="submit">提交人工 Forecast</button>' in html
    assert "Copilot 未配置，人工流程可用" in html
