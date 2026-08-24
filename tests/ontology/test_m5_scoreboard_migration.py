from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository import schema, schema_scoreboard
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.scoreboard.models import (
    ScoreboardObservationRow,
    ScoreboardShadowReviewRow,
)
from nutmeg.ontology.wiring import build_ontology_kernel

AT = "2026-08-24T10:00:00+00:00"
SCOREBOARD_PERMISSIONS = {
    ("record_scoreboard_observation", "judge_operator"),
    ("approve_scoreboard_cutover", "judge_operator"),
    ("record_scoreboard_shadow_review", "deterministic_system"),
    ("record_scoreboard_export", "deterministic_system"),
}


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    report = kernel.initialize()
    return kernel, report


def _artifact(kernel, key: str) -> tuple[str, str]:
    outcome = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=f'{{"key":"{key}"}}'.encode(),
            content_type="application/json",
            source_name="m5-test",
            source_type="fixture",
            actor_id="source:m5-test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key=f"m5:artifact:{key}",
            retrieved_at=datetime(2026, 8, 24, 10, tzinfo=UTC),
        )
    )
    artifact_id = next(
        ref.object_id
        for ref in outcome.result_refs
        if ref.object_type == "source_artifact"
    )
    return outcome.action_id, artifact_id


def _observation(
    observation_id: str,
    action_id: str,
    *,
    supersedes: str | None = None,
) -> ScoreboardObservationRow:
    return ScoreboardObservationRow(
        scoreboard_observation_id=observation_id,
        group_key="adjudications",
        metric_key="rejected_evidence_coverage",
        tally="4/5",
        detail="four of five decisions record rejected evidence",
        status="active",
        numerator=4.0,
        denominator=5.0,
        value=0.8,
        unit="ratio",
        evidence_refs=[{"object_type": "adjudication", "object_id": "adj-1"}],
        effective_at=AT,
        recorded_at=AT,
        supersedes_observation_id=supersedes,
        action_id=action_id,
    )


def test_migration_13_seeds_legacy_authority_and_exact_permissions(
    tmp_path: Path,
) -> None:
    kernel, report = _kernel(tmp_path)

    assert report.applied_versions[-1] == 13
    assert {
        "scoreboard_observations",
        "scoreboard_shadow_reviews",
        "scoreboard_authority",
    } <= set(inspect(kernel.engine).get_table_names())
    with kernel.engine.connect() as connection:
        rows = connection.execute(select(schema.action_permissions)).mappings().all()
        authority = connection.execute(
            select(schema_scoreboard.scoreboard_authority)
        ).mappings().one()

    seeded = {(row["action_type"], row["actor_role"]) for row in rows}
    assert SCOREBOARD_PERMISSIONS <= seeded
    assert not {
        (action_type, role)
        for action_type, _role in SCOREBOARD_PERMISSIONS
        for role in ("ai_analyst", "ai_extractor")
    } & seeded
    assert authority["authority_id"] == "primary"
    assert authority["state"] == "legacy"
    assert authority["version"] == 1


def test_repository_round_trips_observation_revisions_and_latest_as_of(
    tmp_path: Path,
) -> None:
    kernel, _report = _kernel(tmp_path)
    action_one, _artifact_one = _artifact(kernel, "observation-one")
    action_two, _artifact_two = _artifact(kernel, "observation-two")
    first = _observation("sbo-1", action_one)
    second = _observation("sbo-2", action_two, supersedes="sbo-1")

    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.scoreboard.insert_observation(first)
        assert uow.scoreboard.observation("sbo-1") == first
        uow.scoreboard.insert_observation(second)

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.scoreboard.latest_observations(AT) == [second]
        assert uow.scoreboard.count_observations() == 2


def test_repository_records_review_and_updates_authority_optimistically(
    tmp_path: Path,
) -> None:
    kernel, _report = _kernel(tmp_path)
    review_action, legacy_artifact_id = _artifact(kernel, "review")
    approve_action, _approve_artifact = _artifact(kernel, "approve")
    export_action, _export_artifact = _artifact(kernel, "export")
    review = ScoreboardShadowReviewRow(
        scoreboard_shadow_review_id="sbr-1",
        legacy_source_artifact_id=legacy_artifact_id,
        legacy_sha256="a" * 64,
        projection_version="sb-v1",
        source_high_watermark=42,
        classification=[
            {
                "group_key": "adjudications",
                "metric_key": "rejected_evidence_coverage",
                "classification": "matched",
            }
        ],
        matched_count=1,
        manual_count=0,
        corrected_count=0,
        unexplained_count=0,
        status="succeeded",
        reviewed_at=AT,
        action_id=review_action,
    )

    with OntologyUnitOfWork(kernel.engine) as uow:
        uow.scoreboard.insert_shadow_review(review)
        assert uow.scoreboard.shadow_review("sbr-1") == review
        assert uow.scoreboard.latest_shadow_review() == review
        assert uow.scoreboard.authority().state == "legacy"
        approved = uow.scoreboard.approve_authority(
            expected_version=1,
            review_id="sbr-1",
            projection_version="sb-v1",
            source_high_watermark=42,
            legacy_sha256="a" * 64,
            approved_at=AT,
            action_id=approve_action,
        )
        assert approved.state == "ontology"
        assert approved.version == 2

    with OntologyUnitOfWork(kernel.engine) as uow:
        with pytest.raises(OptimisticConcurrencyError, match="expected 1"):
            uow.scoreboard.approve_authority(
                expected_version=1,
                review_id="sbr-1",
                projection_version="sb-v1",
                source_high_watermark=42,
                legacy_sha256="a" * 64,
                approved_at=AT,
                action_id=approve_action,
            )
        exported = uow.scoreboard.record_export(
            expected_version=2,
            export_sha256="b" * 64,
            projection_version="sb-v2",
            source_high_watermark=43,
            action_id=export_action,
        )
        assert exported.compatibility_export_sha256 == "b" * 64
        assert exported.projection_version == "sb-v2"
        assert exported.source_high_watermark == 43
        assert exported.version == 3
        assert uow.scoreboard.count_shadow_reviews() == 1
