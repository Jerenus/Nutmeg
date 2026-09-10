from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.operator.review_actions import (
    OperatorReviewActions,
    RequestScoreboardReviewCompletionRequest,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_workers import (
    ReviewMaterializationWorker,
    ScoreboardReviewCompletionWorker,
)
from tests.ontology.operator.test_judgment_actions import AT
from tests.ontology.operator.test_no_ticket_actions import AT as NO_TICKET_AT
from tests.ontology.operator.test_no_ticket_actions import (
    _fixture as _no_ticket_fixture,
)
from tests.ontology.operator.test_no_ticket_actions import (
    _request as _no_ticket_request,
)
from tests.ontology.operator.test_review_actions import (
    SIGNING_KEY,
    _disposition_request,
    _materialized_review,
    _register_metric,
    _review_fixture,
    _seed_bound_outcome,
)
from tests.ontology.operator.test_review_completion import (
    _record_shadow,
    _review_observation_request,
    _token,
)


def _action_service(engine) -> ActionService:
    return ActionService(lambda: OntologyUnitOfWork(engine))


def test_review_materialization_worker_completes_once_and_replay_is_empty(
    tmp_path: Path,
) -> None:
    fixture = _review_fixture(tmp_path)
    worker = ReviewMaterializationWorker(
        action_service=_action_service(fixture.engine),
        review_actions=fixture.actions,
        worker_id="operator-review-materialization",
        lease_duration=timedelta(minutes=5),
    )

    first = worker.run_once(limit=10, as_of=AT + timedelta(minutes=2))
    replay = worker.run_once(limit=10, as_of=AT + timedelta(minutes=3))

    assert len(first) == 1
    assert first[0].status is ActionStatus.COMMITTED
    assert replay == ()
    with OntologyUnitOfWork(fixture.engine) as uow:
        review = uow.operator_review.review_for_eligibility_fact(fixture.fact_id)
        jobs = uow.operator_review.materialization_jobs_for_fact(fixture.fact_id)
    assert review is not None
    assert len(jobs) == 1 and jobs[0].state == "completed"


def test_review_materialization_worker_requeues_until_bound_outcomes_exist(
    tmp_path: Path,
) -> None:
    source = _no_ticket_fixture(tmp_path)
    closed = source.actions.record_no_ticket(
        _no_ticket_request(source, key="review-worker:forecast-no-ticket")
    )
    fact_id = next(
        ref.object_id
        for ref in closed.result_refs
        if ref.object_type == "operator_review_eligibility_fact"
    )
    worker = ReviewMaterializationWorker(
        action_service=_action_service(source.engine),
        review_actions=OperatorReviewActions(
            _action_service(source.engine),
            shadow_token_signing_key=SIGNING_KEY,
        ),
        worker_id="operator-review-materialization",
        lease_duration=timedelta(minutes=5),
    )

    waiting = worker.run_once(limit=10, as_of=NO_TICKET_AT + timedelta(minutes=2))
    with OntologyUnitOfWork(source.engine) as uow:
        queued = uow.operator_review.materialization_jobs_for_fact(fact_id)[0]
    assert waiting == ()
    assert queued.state == "queued"
    assert queued.last_error_code == "review_not_ready"

    outcome_id = _seed_bound_outcome(source.engine)
    completed = worker.run_once(limit=10, as_of=NO_TICKET_AT + timedelta(minutes=4))

    assert len(completed) == 1
    with OntologyUnitOfWork(source.engine) as uow:
        review = uow.operator_review.review_for_eligibility_fact(fact_id)
    assert review is not None
    assert review.outcome_revision_ids == (outcome_id,)


def test_scoreboard_completion_worker_hashes_authority_and_completes_request(
    tmp_path: Path,
) -> None:
    fixture, review_id = _materialized_review(tmp_path / "fixture")
    scoreboard_path = tmp_path / "scoreboard.json"
    scoreboard_path.write_text('{"updated_at":"2026-09-05T00:00:00Z"}\n', encoding="utf-8")
    legacy_hash = hashlib.sha256(scoreboard_path.read_bytes()).hexdigest()
    _register_metric(fixture, "metric-a")
    disposition = fixture.actions.record_scoreboard_effect_disposition(
        _disposition_request(review_id)
    )
    disposition_id = disposition.result_refs[0].object_id
    observation = fixture.actions.record_scoreboard_review_observation(
        _review_observation_request(
            review_id,
            disposition_id,
            observed_hash=legacy_hash,
        )
    )
    observation_id = next(
        ref.object_id
        for ref in observation.result_refs
        if ref.object_type == "scoreboard_observation"
    )
    shadow_id, high_watermark = _record_shadow(
        fixture,
        observation_id=observation_id,
        key="review-worker:shadow",
        legacy_hash=legacy_hash,
    )
    requested = fixture.actions.request_scoreboard_review_completion(
        RequestScoreboardReviewCompletionRequest(
            review_id=review_id,
            expected_disposition_revision_id=disposition_id,
            shadow_review_token=_token(
                shadow_review_id=shadow_id,
                source_high_watermark=high_watermark,
                legacy_hash=legacy_hash,
            ),
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="review-worker:completion-request",
            requested_at=AT + timedelta(minutes=7),
        )
    )
    request_id = requested.result_refs[0].object_id
    worker = ScoreboardReviewCompletionWorker(
        action_service=_action_service(fixture.engine),
        review_actions=fixture.actions,
        scoreboard_path=scoreboard_path,
        worker_id="operator-scoreboard-review-completion",
        lease_duration=timedelta(minutes=5),
    )

    completed = worker.run_once(limit=10, as_of=AT + timedelta(minutes=8))
    replay = worker.run_once(limit=10, as_of=AT + timedelta(minutes=9))

    assert len(completed) == 1
    assert completed[0].status is ActionStatus.COMMITTED
    assert replay == ()
    with OntologyUnitOfWork(fixture.engine) as uow:
        receipt = uow.operator_review.completion_receipt_for_review(review_id)
        jobs = uow.operator_review.completion_jobs_for_request(request_id)
    assert receipt is not None
    assert receipt.post_update_legacy_sha256 == legacy_hash
    assert len(jobs) == 1 and jobs[0].state == "completed"
