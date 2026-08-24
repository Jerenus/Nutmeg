from datetime import UTC, datetime

import pytest

from nutmeg.analytics.calibrate_flow import CalibrateRequest
from nutmeg.ontology.actions.models import ActorRole, ObjectRef
from nutmeg.ontology.actions.scoreboard_actions import RecordScoreboardObservationRequest
from nutmeg.product.repository import ProductReadRepository

AT = datetime(2026, 8, 24, 10, tzinfo=UTC)


def test_missing_duckdb_returns_degraded_projection_without_creating_it(
    seeded_product,
) -> None:
    path = seeded_product.settings.analytics_db_path
    repository = ProductReadRepository(seeded_product.kernel.engine, path)

    result = repository.scoreboard_projection(as_of=AT.isoformat())

    assert result["health"]["state"] == "unavailable"
    assert result["health"]["code"] == "projection_unavailable"
    assert result["rows"] == []
    assert not path.exists()


def test_repository_reads_last_good_projection_and_marks_stale_after_new_action(
    seeded_product,
) -> None:
    kernel = seeded_product.kernel
    kernel.scoreboard_actions.record_observation(
        RecordScoreboardObservationRequest(
            group_key="chains",
            metric_key="main",
            tally="1/1",
            detail="manual metric",
            status="active",
            numerator=1.0,
            denominator=1.0,
            value=1.0,
            unit="ratio",
            evidence_refs=[ObjectRef("adjudication", "adj-1")],
            effective_at=AT,
            supersedes_observation_id=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m5:product:manual",
            requested_at=AT,
        )
    )
    build = kernel.calibrate.build(
        CalibrateRequest(
            as_of=AT.isoformat(),
            built_at="2026-08-24T10:05:00+00:00",
        )
    )
    repository = ProductReadRepository(kernel.engine, kernel.paths.analytics)

    current = repository.scoreboard_projection(as_of=AT.isoformat())
    assert current["health"]["state"] == "available"
    assert current["health"]["source_high_watermark"] == build.high_watermark
    assert {row["plane"] for row in current["rows"]} >= {
        "forecast",
        "money",
        "intervention",
        "lifecycle",
        "manual",
    }

    kernel.scoreboard_actions.record_observation(
        RecordScoreboardObservationRequest(
            group_key="chains",
            metric_key="hedge",
            tally="0/1",
            detail="newer manual fact",
            status="active",
            numerator=0.0,
            denominator=1.0,
            value=0.0,
            unit="ratio",
            evidence_refs=[ObjectRef("adjudication", "adj-2")],
            effective_at=AT,
            supersedes_observation_id=None,
            actor_id="operator:jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="m5:product:manual:stale",
            requested_at=AT,
        )
    )
    stale = repository.scoreboard_projection(as_of=AT.isoformat())
    assert stale["health"]["state"] == "stale"
    assert stale["health"]["code"] == "projection_stale"
    assert stale["rows"] == current["rows"]


def test_ontology_browser_is_allowlisted_temporal_searchable_and_cursor_stable(
    seeded_product,
) -> None:
    repository = ProductReadRepository(
        seeded_product.kernel.engine,
        seeded_product.settings.analytics_db_path,
    )
    before = datetime(2026, 8, 24, 10, tzinfo=UTC).isoformat()

    first = repository.ontology_objects(
        object_type="team",
        query="FC",
        after=None,
        limit=1,
        as_of=before,
    )
    second = repository.ontology_objects(
        object_type="team",
        query="FC",
        after=first["next_cursor"],
        limit=1,
        as_of=before,
    )

    assert len(first["items"]) == 1
    assert len(second["items"]) == 1
    assert first["items"][0]["object_id"] != second["items"][0]["object_id"]
    assert first["next_cursor"] is not None
    assert second["next_cursor"] is None
    with pytest.raises(ValueError, match="not allowlisted"):
        repository.ontology_objects(
            object_type="source_artifacts",
            query=None,
            after=None,
            limit=10,
            as_of=before,
        )


def test_ontology_detail_exposes_typed_properties_lineage_and_history_only(
    seeded_product,
) -> None:
    repository = ProductReadRepository(
        seeded_product.kernel.engine,
        seeded_product.settings.analytics_db_path,
    )

    detail = repository.ontology_object("match", "match-1", as_of=AT.isoformat())

    assert detail is not None
    assert detail["object_type"] == "match"
    assert detail["object_id"] == "match-1"
    assert detail["properties"]["current_revision_id"] == "mr-before"
    assert detail["versions"][0]["match_revision_id"] == "mr-before"
    serialized = str(detail)
    assert "SELECT " not in serialized
    assert "storage_path" not in serialized
    assert "payload_json" not in serialized
