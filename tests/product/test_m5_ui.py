import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.interfaces.product_api import create_product_app
from nutmeg.product.contracts import (
    ActionView,
    CalibrationResponse,
    CounterfactualReplaySummary,
    FactorEstimateSummary,
    LifecycleProposalSummary,
    LineageEdge,
    MetricSummary,
    ObjectRefContract,
    OntologyObjectDetail,
    OntologyObjectPage,
    OntologyObjectSummary,
    ProjectionHealth,
    RegimeSummary,
    ReviewResponse,
    ScorePlaneSummary,
    SettlementSummary,
)

from .conftest import CLOCK


def _health() -> ProjectionHealth:
    return ProjectionHealth(
        state="available",
        projection_version="sb-v1",
        source_high_watermark=17,
        built_at="2026-08-24T10:00:00Z",
        cohort_definition_version="cohort-v1",
        metric_version="scoring-v1",
    )


def _plane(name: str, value: float | None, status: str) -> ScorePlaneSummary:
    return ScorePlaneSummary(
        plane=name,
        health=_health(),
        metrics=[
            MetricSummary(
                group_key=f"{name}:all",
                metric_key="coverage" if value is not None else "unscored_sample",
                value=value,
                numerator=1 if value is not None else None,
                denominator=2,
                unit="ratio",
                status=status,
                detail="fixture metric",
                source_refs=[
                    ObjectRefContract(object_type="projection", object_id="sb-v1")
                ],
            )
        ],
    )


class _M5Queries:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def review(self, *, as_of):
        return ReviewResponse(
            as_of=as_of,
            forecast=_plane("forecast", 0.5, "available"),
            money=_plane("money", -20.0, "available"),
            intervention=_plane("intervention", None, "unscored"),
            settlements=[
                SettlementSummary(
                    ticket_settlement_id="settlement-1",
                    ticket_id="ticket-1",
                    status="settled",
                    settled_at="2026-08-24T09:30:00Z",
                    stake_amount=100,
                    payout_amount=80,
                    pnl_amount=-20,
                    settlement_method_version="odds-faithful-v1",
                    leg_settlement_ids=["leg-settlement-1"],
                )
            ],
            counterfactuals=[
                CounterfactualReplaySummary(
                    adjudication_id="adjudication-" + "a" * 48,
                    subject_type="match",
                    subject_id="match-1",
                    match_id="match-1",
                    outcome_id="outcome-1",
                    market_definition_id="md-had",
                    label="late alternative",
                    eligibility_code="recorded_after_outcome",
                    brier=None,
                    adjudication_created_at="2026-08-24T10:00:00Z",
                    outcome_recorded_at="2026-08-24T09:00:00Z",
                )
            ],
        )

    def calibration(self, *, as_of):
        return CalibrationResponse(
            as_of=as_of,
            health=ProjectionHealth(
                **{
                    **_health().model_dump(),
                    "projection_version": "fe-v1",
                }
            ),
            factors=[
                FactorEstimateSummary(
                    factor_definition_id="factor-rest",
                    factor_family="rest",
                    factor_version=3,
                    scope_key="competition:fixture",
                    market_definition_id="md-had",
                    cohort_key="factor_family_scope_market",
                    n_eff=12,
                    raw_mean=0.08,
                    shrunk_mean=0.04,
                    interval_low=0.01,
                    interval_high=0.07,
                    current_status="probation",
                )
            ],
            lifecycle_proposals=[
                LifecycleProposalSummary(
                    proposal_id="factor-rest:probation->active",
                    factor_definition_id="factor-rest",
                    from_status="probation",
                    to_status="active",
                    rationale={"n_eff": 12, "interval_low": 0.01},
                    policy_version="lifecycle-v1",
                )
            ],
            regimes=[
                RegimeSummary(
                    regime_key="match:match-1",
                    values={"labels": ["balanced"], "scope_id": "match-1"},
                )
            ],
        )

    def ontology_objects(
        self, *, object_type, query, after, limit, as_of
    ) -> OntologyObjectPage:
        assert limit <= 100
        return OntologyObjectPage(
            object_type=object_type,
            as_of=as_of,
            items=[
                OntologyObjectSummary(
                    object_type=object_type,
                    object_id="match-" + "f" * 56,
                    label="Home FC vs Away FC",
                    status="scheduled",
                    recorded_at="2026-08-24T08:00:00Z",
                )
            ],
            next_cursor="cursor-next" if after is None else None,
        )

    def ontology_object(self, object_type, object_id, *, as_of):
        return OntologyObjectDetail(
            object_type=object_type,
            object_id=object_id,
            as_of=as_of,
            properties={"status": "scheduled", "version": 2},
            links=[
                LineageEdge(
                    relation="has_team",
                    source=ObjectRefContract(
                        object_type="match", object_id=object_id
                    ),
                    target=ObjectRefContract(
                        object_type="team", object_id="team-home"
                    ),
                )
            ],
            versions=[{"version": 1}, {"version": 2}],
            actions=[
                ActionView(
                    action_id="action-1",
                    action_type="upsert_match",
                    actor_id="operator:owner",
                    actor_role="judge_operator",
                    requested_at="2026-08-24T08:00:00Z",
                    status="committed",
                    result_refs=[],
                    committed_at="2026-08-24T08:00:00Z",
                )
            ],
        )


@pytest.fixture
def client(m3_product_services) -> TestClient:
    services = SimpleNamespace(
        kernel=m3_product_services.kernel,
        queries=_M5Queries(m3_product_services.queries),
        actions=m3_product_services.actions,
        settings=m3_product_services.settings,
        copilot=None,
        tickets=object(),
    )
    return TestClient(
        create_product_app(
            services,
            session_secret="m5-ui-session",
            csrf_secret="m5-ui-csrf",
            clock=lambda: CLOCK,
        )
    )


def test_review_workspace_separates_planes_and_preserves_unscored_rows(
    client: TestClient,
) -> None:
    response = client.get("/review?as_of=2026-08-24T10:00:00Z")

    assert response.status_code == 200
    html = response.text
    assert 'data-workspace="review"' in html
    assert 'data-score-plane="forecast"' in html
    assert 'data-score-plane="money"' in html
    assert 'data-score-plane="intervention"' in html
    assert html.index('data-score-plane="forecast"') < html.index(
        'data-score-plane="money"'
    ) < html.index('data-score-plane="intervention"')
    assert "1 / 2" in html
    assert "sb-v1" in html and "HWM 17" in html
    assert "odds-faithful-v1" in html
    assert "recorded_after_outcome" in html
    assert "未评分" in html
    assert "— / 2" in html
    assert "0 / 2" not in html
    assert 'data-action="record-scoreboard-observation"' in html
    assert 'name="actor_role"' not in html
    assert 'name="actor_id"' not in html


def test_calibration_workspace_has_governed_apply_reject_controls(
    client: TestClient,
) -> None:
    response = client.get("/calibration?as_of=2026-08-24T10:00:00Z")

    assert response.status_code == 200
    html = response.text
    assert 'data-workspace="calibration"' in html
    assert "factor-rest" in html
    assert "0.0100" in html and "0.0700" in html
    assert "n=12" in html
    assert "cohort-v1" in html
    assert 'data-action="factor-lifecycle-adjudication"' in html
    assert 'data-factor-version="3"' in html
    assert 'name="reason"' in html
    assert 'value="apply"' in html
    assert 'value="reject"' in html
    assert 'name="actor_role"' not in html


def test_ontology_workspace_is_allowlisted_paginated_and_renders_lineage(
    client: TestClient,
) -> None:
    response = client.get(
        "/ontology?type=match&q=Home&object_id=match-1&as_of="
        "2026-08-24T10:00:00Z"
    )

    assert response.status_code == 200
    html = response.text
    assert 'data-workspace="ontology"' in html
    assert '<option value="match" selected' in html
    assert "cursor-next" in html
    assert "match-" + "f" * 56 in html
    assert "has_team" in html
    assert "upsert_match" in html
    assert "版本 2" in html
    assert "raw SQL" not in html
    assert 'name="sql"' not in html


def test_m5_navigation_css_and_javascript_preserve_authority_boundaries(
    client: TestClient,
) -> None:
    review = client.get("/review").text
    calibration = client.get("/calibration").text
    ontology = client.get("/ontology?type=match").text
    css = client.get("/assets/product/app.css").text
    script = client.get("/assets/product/app.js").text

    assert 'href="/review"' in review
    assert 'href="/calibration"' in calibration
    assert 'href="/ontology"' in ontology
    assert re.search(
        r"\.score-plane-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,",
        css,
        re.DOTALL,
    )
    narrow = css.split("@media (max-width: 760px)", maxsplit=1)[1]
    assert re.search(
        r"\.score-plane-grid[^\{]*\{[^}]*grid-template-columns:\s*1fr;",
        narrow,
        re.DOTALL,
    )
    assert ".m5-control" in css and "min-height: 44px" in css
    assert "overflow-wrap: anywhere" in css
    assert 'action_type: "record_scoreboard_observation"' in script
    assert 'action_type: "apply_factor_status"' in script
    assert 'action_type: "record_adjudication"' in script
    assert "proposal_id: form.dataset.proposalId" in script
    assert "actor_role" not in script
    for forbidden in (
        "brier =",
        "pnl =",
        "coverage =",
        "counterfactualScore",
        "lifecycleDecision",
        "scoreboardCutover",
    ):
        assert forbidden.casefold() not in script.casefold()
