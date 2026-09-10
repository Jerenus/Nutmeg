from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from nutmeg.ontology.actions.models import ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.actions.scoreboard_actions import (
    RecordScoreboardObservationRequest,
    RecordScoreboardShadowReviewRequest,
    ScoreboardActions,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.review_actions import (
    CompleteScoreboardReviewRequest,
    RecordScoreboardReviewObservationRequest,
    RequestScoreboardReviewCompletionRequest,
    ShadowReviewTokenCodec,
    ShadowReviewTokenPayload,
)
from nutmeg.ontology.repository.operator_decision import OperatorDecisionRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.operator.test_judgment_actions import AT
from tests.ontology.operator.test_review_actions import (
    SIGNING_KEY,
    ReviewFixture,
    _disposition_request,
    _materialized_review,
    _register_metric,
)

POST_HASH = "b" * 64


def _review_observation_request(
    review_id: str,
    disposition_id: str,
    *,
    metric_key: str = "metric-a",
    observed_hash: str = POST_HASH,
    key: str = "review-completion:observation",
) -> RecordScoreboardReviewObservationRequest:
    return RecordScoreboardReviewObservationRequest(
        review_id=review_id,
        expected_disposition_revision_id=disposition_id,
        observed_legacy_sha256=observed_hash,
        observation=RecordScoreboardObservationRequest(
            group_key="review-effect",
            metric_key=metric_key,
            tally="1/1",
            detail="The externally governed scoreboard update is now observed.",
            status="active",
            numerator=1.0,
            denominator=1.0,
            value=1.0,
            unit="ratio",
            evidence_refs=[ObjectRef("operator_review", review_id)],
            effective_at=AT + timedelta(minutes=5),
            supersedes_observation_id=None,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=key,
            requested_at=AT + timedelta(minutes=5),
        ),
    )


def _effect_review(tmp_path: Path):
    fixture, review_id = _materialized_review(tmp_path)
    _register_metric(fixture, "metric-a")
    disposition = fixture.actions.record_scoreboard_effect_disposition(
        _disposition_request(review_id)
    )
    disposition_id = disposition.result_refs[0].object_id
    observation = fixture.actions.record_scoreboard_review_observation(
        _review_observation_request(review_id, disposition_id)
    )
    observation_id = next(
        ref.object_id
        for ref in observation.result_refs
        if ref.object_type == "scoreboard_observation"
    )
    observation_action_id = observation.action_id
    return fixture, review_id, disposition_id, observation_id, observation_action_id


def _record_shadow(
    fixture: ReviewFixture,
    *,
    observation_id: str,
    key: str,
    legacy_hash: str = POST_HASH,
    source_high_watermark: int | None = None,
    relevant_classification: str = "formal_manual",
    include_irrelevant_unexplained: bool = False,
):
    scoreboard = ScoreboardActions(ActionService(lambda: OntologyUnitOfWork(fixture.engine)))
    with fixture.engine.connect() as connection:
        current_high_watermark = int(
            connection.scalar(text("SELECT COALESCE(MAX(rowid), 0) FROM actions"))
        )
    high_watermark = (
        current_high_watermark
        if source_high_watermark is None
        else source_high_watermark
    )
    classification = [
        {
            "group_key": "review-effect",
            "metric_key": "metric-a",
            "classification": relevant_classification,
            "target_ref": f"scoreboard_observation:{observation_id}",
        }
    ]
    if include_irrelevant_unexplained:
        classification.append(
            {
                "group_key": "other-review",
                "metric_key": "other-metric",
                "classification": "unexplained",
                "target_ref": "legacy:other-metric",
            }
        )
    counts = {
        "matched": sum(row["classification"] == "matched" for row in classification),
        "formal_manual": sum(
            row["classification"] == "formal_manual" for row in classification
        ),
        "source_correction": sum(
            row["classification"] == "source_correction" for row in classification
        ),
        "unexplained": sum(
            row["classification"] == "unexplained" for row in classification
        ),
    }
    outcome = scoreboard.record_shadow_review(
        RecordScoreboardShadowReviewRequest(
            legacy_source_artifact_id="artifact-1",
            legacy_sha256=legacy_hash,
            projection_version="scoreboard-review-test-v1",
            source_high_watermark=high_watermark,
            classification=classification,
            matched_count=counts["matched"],
            manual_count=counts["formal_manual"],
            corrected_count=counts["source_correction"],
            unexplained_count=counts["unexplained"],
            status="succeeded",
            actor_id="system:scoreboard",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key=key,
            requested_at=AT + timedelta(minutes=6),
        )
    )
    review_id = outcome.result_refs[0].object_id
    return review_id, high_watermark


def _token(
    *,
    shadow_review_id: str,
    source_high_watermark: int,
    legacy_hash: str = POST_HASH,
    metric_keys: tuple[str, ...] = ("metric-a",),
) -> str:
    return ShadowReviewTokenCodec(SIGNING_KEY).encode(
        ShadowReviewTokenPayload(
            shadow_review_id=shadow_review_id,
            source_high_watermark=source_high_watermark,
            compared_legacy_sha256=legacy_hash,
            metric_keys=metric_keys,
        )
    )


def _request_completion(
    fixture: ReviewFixture,
    *,
    review_id: str,
    disposition_id: str,
    token: str,
    key: str = "review-completion:request",
):
    return fixture.actions.request_scoreboard_review_completion(
        RequestScoreboardReviewCompletionRequest(
            review_id=review_id,
            expected_disposition_revision_id=disposition_id,
            shadow_review_token=token,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=key,
            requested_at=AT + timedelta(minutes=7),
        )
    )


def _claim_completion(fixture: ReviewFixture):
    with OntologyUnitOfWork(fixture.engine) as uow:
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="scoreboard_review_completion",
            lease_owner="scoreboard-completion-worker",
            as_of=(AT + timedelta(minutes=8)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=13)).isoformat(),
            limit=1,
        )
    assert len(claimed) == 1
    return claimed[0]


def _complete_request(completion_request_id: str, worker_job_id: str):
    return CompleteScoreboardReviewRequest(
        completion_request_id=completion_request_id,
        worker_job_id=worker_job_id,
        lease_owner="scoreboard-completion-worker",
        current_legacy_sha256=POST_HASH,
        actor_id="system:operator-review",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        requested_at=AT + timedelta(minutes=9),
    )


def test_observation_link_requires_current_effect_disposition_and_one_common_hash(
    tmp_path: Path,
) -> None:
    fixture, review_id = _materialized_review(tmp_path)
    _register_metric(fixture, "metric-a")
    _register_metric(fixture, "metric-b")
    disposition = fixture.actions.record_scoreboard_effect_disposition(
        _disposition_request(
            review_id,
            metric_keys=("metric-a", "metric-b"),
        )
    )
    disposition_id = disposition.result_refs[0].object_id
    first = fixture.actions.record_scoreboard_review_observation(
        _review_observation_request(review_id, disposition_id)
    )
    assert first.status is ActionStatus.COMMITTED

    with pytest.raises(ValueError, match="already linked"):
        fixture.actions.record_scoreboard_review_observation(
            _review_observation_request(
                review_id,
                disposition_id,
                key="review-completion:duplicate-observation",
            )
        )
    with pytest.raises(ValueError, match="required metric"):
        fixture.actions.record_scoreboard_review_observation(
            _review_observation_request(
                review_id,
                disposition_id,
                metric_key="unknown-metric",
                key="review-completion:wrong-metric",
            )
        )
    with pytest.raises(ValueError, match="same post-update"):
        fixture.actions.record_scoreboard_review_observation(
            _review_observation_request(
                review_id,
                disposition_id,
                metric_key="metric-b",
                observed_hash="c" * 64,
                key="review-completion:wrong-hash",
            )
        )


def test_completion_uses_exact_selected_shadow_token_not_latest_global_review(
    tmp_path: Path,
) -> None:
    fixture, review_id, disposition_id, observation_id, observation_action_id = (
        _effect_review(tmp_path)
    )
    selected_id, selected_high_watermark = _record_shadow(
        fixture,
        observation_id=observation_id,
        key="review-completion:shadow:selected",
        include_irrelevant_unexplained=True,
    )
    latest_id, _ = _record_shadow(
        fixture,
        observation_id=observation_id,
        key="review-completion:shadow:newer",
    )
    assert latest_id != selected_id
    selected_token = _token(
        shadow_review_id=selected_id,
        source_high_watermark=selected_high_watermark,
    )
    requested = _request_completion(
        fixture,
        review_id=review_id,
        disposition_id=disposition_id,
        token=selected_token,
    )
    replayed_request = _request_completion(
        fixture,
        review_id=review_id,
        disposition_id=disposition_id,
        token=selected_token,
    )
    assert requested == replayed_request
    request_id = requested.result_refs[0].object_id
    job = _claim_completion(fixture)
    completed = fixture.actions.complete_scoreboard_review(
        _complete_request(request_id, job.worker_job_id)
    )
    replayed_completion = fixture.actions.complete_scoreboard_review(
        _complete_request(request_id, job.worker_job_id)
    )

    assert completed.status is ActionStatus.COMMITTED
    assert replayed_completion == completed
    with OntologyUnitOfWork(fixture.engine) as uow:
        receipt = uow.operator_review.completion_receipt_for_review(review_id)
        requests = uow.operator_review.completion_requests_for_review(review_id)
        jobs = uow.operator_review.completion_jobs_for_request(request_id)
    assert receipt is not None
    assert receipt.shadow_review_id == selected_id
    assert receipt.shadow_review_id != latest_id
    assert receipt.shadow_source_high_watermark == selected_high_watermark
    assert receipt.post_update_legacy_sha256 == POST_HASH
    assert receipt.observation_action_ids == (observation_action_id,)
    assert len(requests) == 1
    assert len(jobs) == 1 and jobs[0].state == "completed"


@pytest.mark.parametrize(
    ("case", "error"),
    (
        ("wrong_id", "shadow review"),
        ("wrong_hash", "legacy hash"),
        ("wrong_metric_set", "metric set"),
        ("wrong_high_watermark", "high water"),
        ("relevant_unexplained", "unexplained"),
        ("observation_below_high_water", "high water"),
    ),
)
def test_completion_rejects_every_mismatched_selected_shadow_binding(
    tmp_path: Path,
    case: str,
    error: str,
) -> None:
    fixture, review_id, disposition_id, observation_id, observation_action_id = (
        _effect_review(tmp_path)
    )
    del observation_action_id
    with fixture.engine.connect() as connection:
        observation_rowid = int(
            connection.scalar(
                text("SELECT rowid FROM actions WHERE idempotency_key = "
                     "'review-completion:observation'")
            )
        )
    relevant = "unexplained" if case == "relevant_unexplained" else "formal_manual"
    requested_high_watermark = (
        observation_rowid - 1
        if case == "observation_below_high_water"
        else None
    )
    shadow_id, high_watermark = _record_shadow(
        fixture,
        observation_id=observation_id,
        key=f"review-completion:shadow:{case}",
        source_high_watermark=requested_high_watermark,
        relevant_classification=relevant,
    )
    token_id = "sbr-does-not-exist" if case == "wrong_id" else shadow_id
    token_hash = "c" * 64 if case == "wrong_hash" else POST_HASH
    token_metrics = ("other-metric",) if case == "wrong_metric_set" else ("metric-a",)
    token_high_watermark = (
        high_watermark + 1 if case == "wrong_high_watermark" else high_watermark
    )
    token = _token(
        shadow_review_id=token_id,
        source_high_watermark=token_high_watermark,
        legacy_hash=token_hash,
        metric_keys=token_metrics,
    )
    requested = _request_completion(
        fixture,
        review_id=review_id,
        disposition_id=disposition_id,
        token=token,
    )
    job = _claim_completion(fixture)

    with pytest.raises(ValueError, match=error):
        fixture.actions.complete_scoreboard_review(
            replace(
                _complete_request(requested.result_refs[0].object_id, job.worker_job_id),
                current_legacy_sha256=token_hash,
            )
        )
    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.operator_review.completion_receipt_for_review(review_id) is None


def test_completion_receipt_and_worker_transition_roll_back_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, review_id, disposition_id, observation_id, _ = _effect_review(tmp_path)
    shadow_id, high_watermark = _record_shadow(
        fixture,
        observation_id=observation_id,
        key="review-completion:shadow:rollback",
    )
    requested = _request_completion(
        fixture,
        review_id=review_id,
        disposition_id=disposition_id,
        token=_token(
            shadow_review_id=shadow_id,
            source_high_watermark=high_watermark,
        ),
    )
    job = _claim_completion(fixture)
    original = OperatorDecisionRepository.complete_worker_job

    def complete_then_fail(repository, **kwargs):
        original(repository, **kwargs)
        raise RuntimeError("injected worker transition failure")

    monkeypatch.setattr(
        OperatorDecisionRepository,
        "complete_worker_job",
        complete_then_fail,
    )
    with pytest.raises(RuntimeError, match="injected"):
        fixture.actions.complete_scoreboard_review(
            _complete_request(requested.result_refs[0].object_id, job.worker_job_id)
        )

    with OntologyUnitOfWork(fixture.engine) as uow:
        assert uow.operator_review.completion_receipt_for_review(review_id) is None
        persisted_job = uow.operator_decision.worker_job(job.worker_job_id)
    assert persisted_job is not None and persisted_job.state == "leased"
