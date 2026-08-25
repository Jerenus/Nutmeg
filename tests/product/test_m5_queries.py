from datetime import UTC, datetime

import pytest

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.queries import ProductQueryService
from nutmeg.product.repository import ProductReadRepository

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _queries(seeded_product) -> ProductQueryService:
    repository = ProductReadRepository(
        seeded_product.kernel.engine,
        seeded_product.kernel.paths.analytics,
    )
    return ProductQueryService(repository, seeded_product.kernel)


def test_review_and_scoreboard_degrade_without_hiding_operational_truth(
    seeded_product,
) -> None:
    queries = _queries(seeded_product)

    review = queries.review(as_of=AT)
    scoreboard = queries.scoreboard(as_of=AT)

    assert review.forecast.health.state == "unavailable"
    assert review.money.health.state == "unavailable"
    assert review.intervention.health.state == "unavailable"
    assert review.settlements == []
    assert scoreboard.authority.state == "legacy"
    assert {plane.plane for plane in scoreboard.planes} == {
        "forecast",
        "money",
        "intervention",
        "lifecycle",
        "manual",
    }
    assert scoreboard.health.code == "projection_unavailable"
    assert not seeded_product.kernel.paths.analytics.exists()


def test_calibration_reports_successful_empty_projection_as_available(
    seeded_product,
) -> None:
    seeded_product.kernel.calibrate.build(
        CalibrateRequest(
            as_of=AT.isoformat(),
            built_at="2026-08-24T10:05:00+00:00",
        )
    )

    calibration = _queries(seeded_product).calibration(as_of=AT)

    assert calibration.health.state == "available"
    assert calibration.health.projection_version == "fe-v1"
    assert calibration.factors == []
    assert calibration.lifecycle_proposals == []


def test_ontology_queries_are_temporal_allowlisted_and_not_found_is_explicit(
    seeded_product,
) -> None:
    queries = _queries(seeded_product)

    first = queries.ontology_objects(
        object_type="team", query="FC", after=None, limit=1, as_of=AT
    )
    second = queries.ontology_objects(
        object_type="team",
        query="FC",
        after=first.next_cursor,
        limit=1,
        as_of=AT,
    )
    detail = queries.ontology_object("match", "match-1", as_of=AT)

    assert first.items[0].object_id != second.items[0].object_id
    assert detail.properties["current_revision_id"] == "mr-before"
    assert detail.as_of == AT
    with pytest.raises(ValueError, match="not allowlisted"):
        queries.ontology_objects(
            object_type="source_artifacts",
            query=None,
            after=None,
            limit=10,
            as_of=AT,
        )
    with pytest.raises(ProductNotFoundError, match="absent"):
        queries.ontology_object("match", "absent", as_of=AT)


def test_m5_queries_require_timezone_aware_as_of(seeded_product) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _queries(seeded_product).review(as_of=datetime(2026, 8, 24, 10))
