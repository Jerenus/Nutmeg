from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nutmeg.product.contracts import (
    MetricSummary,
    OntologyObjectPage,
    ProjectionHealth,
    ProjectionState,
    ReviewResponse,
    ScorePlaneSummary,
)

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def test_projection_and_metric_contracts_are_strict_and_preserve_missing_values() -> None:
    health = ProjectionHealth(
        state=ProjectionState.UNAVAILABLE,
        code="projection_unavailable",
        instruction="run nutmeg ontology calibrate",
        projection_version=None,
        source_high_watermark=None,
        built_at=None,
        cohort_definition_version=None,
        metric_version=None,
    )
    metric = MetricSummary(
        group_key="forecast_truth:md-had",
        metric_key="brier_skill",
        value=None,
        numerator=0,
        denominator=0,
        unit="score",
        status="unscored",
        tally=None,
        detail=None,
        source_refs=[],
    )

    assert health.state is ProjectionState.UNAVAILABLE
    assert metric.value is None
    assert metric.denominator == 0
    with pytest.raises(ValidationError, match="extra"):
        ProjectionHealth(
            **health.model_dump(),
            raw_table="scoreboard_metrics",
        )


def test_review_contract_keeps_three_score_planes_separate() -> None:
    health = ProjectionHealth(
        state=ProjectionState.AVAILABLE,
        code=None,
        instruction=None,
        projection_version="sb-v1",
        source_high_watermark=4,
        built_at=AT,
        cohort_definition_version="cohort-v1",
        metric_version="scoring-v1",
    )
    planes = {
        name: ScorePlaneSummary(plane=name, health=health, metrics=[])
        for name in ("forecast", "money", "intervention")
    }
    review = ReviewResponse(
        as_of=AT,
        forecast=planes["forecast"],
        money=planes["money"],
        intervention=planes["intervention"],
        settlements=[],
        counterfactuals=[],
    )

    assert review.forecast.plane == "forecast"
    assert review.money.plane == "money"
    assert review.intervention.plane == "intervention"


def test_ontology_page_rejects_unversioned_or_extra_payload() -> None:
    with pytest.raises(ValidationError):
        OntologyObjectPage(
            schema_version="1",
            object_type="match",
            as_of=AT,
            items=[],
            next_cursor=None,
            sql="SELECT * FROM matches",
        )
