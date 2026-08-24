from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.actions.scoreboard_actions import (
    ApproveScoreboardCutoverRequest,
    RecordScoreboardExportRequest,
    RecordScoreboardObservationRequest,
    RecordScoreboardShadowReviewRequest,
)
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

NOW = datetime(2026, 8, 24, 10, tzinfo=UTC)


def _kernel(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    return kernel


def _legacy_artifact(kernel) -> str:
    outcome = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=b'{"chains":{"main":{"tally":"1/1"}}}',
            content_type="application/json",
            source_name="legacy-scoreboard",
            source_type="fixture",
            actor_id="source:m5-test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="m5:legacy-scoreboard",
            retrieved_at=NOW,
        )
    )
    return next(
        ref.object_id
        for ref in outcome.result_refs
        if ref.object_type == "source_artifact"
    )


def _observation(
    *, role: ActorRole = ActorRole.JUDGE_OPERATOR, key: str = "m5:observation"
) -> RecordScoreboardObservationRequest:
    return RecordScoreboardObservationRequest(
        group_key="chains",
        metric_key="main",
        tally="1/1",
        detail="the manually reviewed chain hit",
        status="active",
        numerator=1.0,
        denominator=1.0,
        value=1.0,
        unit="ratio",
        evidence_refs=[ObjectRef("adjudication", "adj-1")],
        effective_at=NOW,
        supersedes_observation_id=None,
        actor_id="operator:jun",
        actor_role=role,
        idempotency_key=key,
        requested_at=NOW,
    )


def _review(
    artifact_id: str,
    *,
    unexplained: int = 0,
    role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
    key: str = "m5:review",
) -> RecordScoreboardShadowReviewRequest:
    classification = [
        {
            "group_key": "chains",
            "metric_key": "main",
            "classification": (
                "unexplained" if unexplained else "formal_manual"
            ),
            "target_ref": "scoreboard_observation:sbo-1",
        }
    ]
    return RecordScoreboardShadowReviewRequest(
        legacy_source_artifact_id=artifact_id,
        legacy_sha256="a" * 64,
        projection_version="sb-v1",
        source_high_watermark=42,
        classification=classification,
        matched_count=0,
        manual_count=0 if unexplained else 1,
        corrected_count=0,
        unexplained_count=unexplained,
        status="succeeded",
        actor_id="system:scoreboard",
        actor_role=role,
        idempotency_key=key,
        requested_at=NOW,
    )


def test_observation_requires_evidence_and_ai_is_denied(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    with pytest.raises(ValueError, match="evidence_refs cannot be empty"):
        replace(_observation(), evidence_refs=[])

    denied = kernel.scoreboard_actions.record_observation(
        _observation(role=ActorRole.AI_ANALYST, key="m5:observation:denied")
    )

    assert denied.status is ActionStatus.REJECTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.scoreboard.count_observations() == 0


def test_observation_is_idempotent_and_revision_must_exist(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    first = kernel.scoreboard_actions.record_observation(_observation())
    replay = kernel.scoreboard_actions.record_observation(_observation())

    assert first.status is ActionStatus.COMMITTED
    assert replay.action_id == first.action_id
    observation_id = first.result_refs[0].object_id
    revised = kernel.scoreboard_actions.record_observation(
        replace(
            _observation(key="m5:observation:revision"),
            tally="2/2",
            numerator=2.0,
            denominator=2.0,
            supersedes_observation_id=observation_id,
        )
    )
    assert revised.status is ActionStatus.COMMITTED

    with pytest.raises(ValueError, match="does not exist"):
        kernel.scoreboard_actions.record_observation(
            replace(
                _observation(key="m5:observation:missing"),
                supersedes_observation_id="sbo-missing",
            )
        )


def test_shadow_review_enforces_role_and_classification_counts(tmp_path: Path) -> None:
    kernel = _kernel(tmp_path)
    artifact_id = _legacy_artifact(kernel)
    with pytest.raises(ValueError, match="classification counts"):
        replace(_review(artifact_id), manual_count=0)

    denied = kernel.scoreboard_actions.record_shadow_review(
        _review(
            artifact_id,
            role=ActorRole.JUDGE_OPERATOR,
            key="m5:review:denied",
        )
    )
    committed = kernel.scoreboard_actions.record_shadow_review(_review(artifact_id))

    assert denied.status is ActionStatus.REJECTED
    assert committed.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.scoreboard.count_shadow_reviews() == 1


def test_cutover_rechecks_clean_current_review_hash_and_watermark(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    artifact_id = _legacy_artifact(kernel)
    review_outcome = kernel.scoreboard_actions.record_shadow_review(_review(artifact_id))
    review_id = review_outcome.result_refs[0].object_id
    request = ApproveScoreboardCutoverRequest(
        shadow_review_id=review_id,
        legacy_sha256="a" * 64,
        projection_version="sb-v1",
        source_high_watermark=42,
        expected_authority_version=1,
        actor_id="operator:jun",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="m5:cutover",
        requested_at=NOW,
    )

    approved = kernel.scoreboard_actions.approve_cutover(request)
    assert approved.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.scoreboard.authority().state == "ontology"

    with pytest.raises(OptimisticConcurrencyError, match="expected 1"):
        kernel.scoreboard_actions.approve_cutover(
            replace(request, idempotency_key="m5:cutover:stale")
        )


def test_unexplained_review_blocks_cutover_and_export_is_system_only(
    tmp_path: Path,
) -> None:
    kernel = _kernel(tmp_path)
    artifact_id = _legacy_artifact(kernel)
    review = kernel.scoreboard_actions.record_shadow_review(
        _review(artifact_id, unexplained=1)
    )
    with pytest.raises(ValueError, match="unexplained"):
        kernel.scoreboard_actions.approve_cutover(
            ApproveScoreboardCutoverRequest(
                shadow_review_id=review.result_refs[0].object_id,
                legacy_sha256="a" * 64,
                projection_version="sb-v1",
                source_high_watermark=42,
                expected_authority_version=1,
                actor_id="operator:jun",
                actor_role=ActorRole.JUDGE_OPERATOR,
                idempotency_key="m5:cutover:blocked",
                requested_at=NOW,
            )
        )

    export = RecordScoreboardExportRequest(
        export_sha256="b" * 64,
        expected_authority_version=1,
        actor_id="system:scoreboard",
        actor_role=ActorRole.JUDGE_OPERATOR,
        idempotency_key="m5:export:denied",
        requested_at=NOW,
    )
    denied = kernel.scoreboard_actions.record_export(export)
    assert denied.status is ActionStatus.REJECTED
