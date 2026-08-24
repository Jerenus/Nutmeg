import re

from fastapi.testclient import TestClient

from tests.reliability.test_release_policy import COMMIT, _seed_soak, _seed_system

from .test_m6_api import _client, _release_url, _session


def _release_page_url() -> str:
    return (
        "/release?release_version=v1.0.0&candidate_commit="
        f"{COMMIT}&evaluated_at=2026-08-24T12:00:00Z"
    )


def test_release_workspace_ssr_shows_server_gates_soak_and_evidence_slots(
    seeded_product,
) -> None:
    client = _client(seeded_product)

    response = client.get(_release_page_url())

    assert response.status_code == 200
    html = response.text
    assert 'data-workspace="release"' in html
    assert len(re.findall(r'data-release-gate="G[1-6]"', html)) == 6
    assert html.count("missing_evidence") >= 6
    assert 'data-soak-workflow="jczq"' in html
    assert 'data-soak-workflow="zucai"' in html
    assert 'data-evidence-kind="scheduler_authority"' in html
    assert 'data-evidence-kind="backup_restore"' in html
    assert 'data-performance-metric="board_query_ms"' in html
    assert "500 ms" in html
    assert "800 ms" in html
    assert "1000 ms" in html
    assert "2000 ms" in html
    assert 'data-action="approve-release"' not in html
    assert 'href="/release"' in html
    assert "source_refs" not in html
    assert "report_json" not in html


def test_release_workspace_renders_green_approval_and_current_decision(
    seeded_product,
) -> None:
    _seed_system(seeded_product.kernel)
    _seed_soak(seeded_product.kernel)
    client = _client(seeded_product)

    green = client.get(_release_page_url())

    assert green.status_code == 200
    html = green.text
    assert html.count('data-gate-state="passed"') == 6
    assert html.count('data-soak-date="') == 28
    assert 'data-action="approve-release"' in html
    assert 'name="reason"' in html
    assert 'name="actor_id"' not in html
    assert 'name="actor_role"' not in html

    evaluation = client.get(_release_url()).json()
    approval = client.post(
        "/api/v1/actions",
        headers=_session(client),
        json={
            "action_type": "approve_release",
            "idempotency_key": "m6:ui:approve",
            "payload": {
                "release_version": "v1.0.0",
                "candidate_commit": COMMIT,
                "expected_snapshot_sha256": evaluation[
                    "evidence_snapshot_sha256"
                ],
                "reason": "operator reviewed exact release workspace snapshot",
            },
            "expected_versions": {},
        },
    )
    assert approval.status_code == 200

    current = client.get(_release_page_url())
    assert 'data-approval-status="current"' in current.text
    assert "operator reviewed exact release workspace snapshot" in current.text


def test_route_metrics_use_templates_and_release_javascript_has_no_gate_math(
    seeded_product,
) -> None:
    client = _client(seeded_product)
    client.get("/api/v1/matches/match-1?token=do-not-retain")
    client.get(_release_page_url())

    metrics = client.get(
        "/api/v1/reliability/metrics?as_of=2026-08-24T12:00:00Z"
    )
    script = client.get("/assets/product/app.js").text
    css = client.get("/assets/product/app.css").text

    assert metrics.status_code == 200
    routes = metrics.json()["routes"]
    match_metric = next(
        item
        for item in routes
        if item["route_template"] == "/api/v1/matches/{match_id}"
    )
    assert match_metric["request_count"] == 1
    assert "match-1" not in metrics.text
    assert "do-not-retain" not in metrics.text
    assert 'action_type: "approve_release"' in script
    for forbidden in (
        "gates.every",
        "gate.passed",
        "distinct_days >=",
        "inclusive_span_days >=",
        "release.ready =",
    ):
        assert forbidden not in script
    assert re.search(
        r"\.release-gate-list\s*\{[^}]*grid-template-columns:\s*1fr;",
        css,
        re.DOTALL,
    )
    assert re.search(
        r"\.release-approval-control[^\{]*\{[^}]*min-height:\s*44px;",
        css,
        re.DOTALL,
    )


def test_route_metrics_start_empty_for_a_new_app_instance(seeded_product) -> None:
    first: TestClient = _client(seeded_product)
    first.get("/api/v1/matches/match-1")
    assert first.get("/api/v1/reliability/metrics").json()["routes"]

    restarted: TestClient = _client(seeded_product)

    assert restarted.get("/api/v1/reliability/metrics").json()["routes"] == []
