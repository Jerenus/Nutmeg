from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from nutmeg.ontology.actions.models import ActionStatus, ActorRole, ObjectRef
from nutmeg.ontology.actions.scoreboard_actions import (
    RecordScoreboardObservationRequest,
    ScoreboardActions,
)
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.errors import OptimisticConcurrencyError
from nutmeg.ontology.operator.result_actions import SettleTaskRequest
from nutmeg.ontology.operator.review_actions import (
    MaterializeOperatorReviewItemRequest,
    OperatorReviewActions,
    RecordScoreboardEffectDispositionRequest,
    ReviewNotReadyError,
)
from nutmeg.ontology.repository import schema_operator_result as sor
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.operator_review import OperatorReviewRepository
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.operator.test_judgment_actions import AT
from tests.ontology.operator.test_no_ticket_actions import (
    AT as NO_TICKET_AT,
)
from tests.ontology.operator.test_no_ticket_actions import (
    _fixture as _no_ticket_fixture,
)
from tests.ontology.operator.test_no_ticket_actions import (
    _request as _no_ticket_request,
)
from tests.ontology.operator.test_result_ingest import AT as RESULT_AT
from tests.ontology.operator.test_review_migration import (
    _seed_immediate_fact_before_v25,
)
from tests.ontology.operator.test_task_settlement import (
    _placed_result_set,
    _settlement_request,
)

SIGNING_KEY = "review-signing-key-for-tests-32-bytes-minimum"


@dataclass(frozen=True, slots=True)
class ReviewFixture:
    engine: object
    actions: OperatorReviewActions
    fact_id: str
    job_id: str


def _review_fixture(tmp_path: Path) -> ReviewFixture:
    engine, fact_id = _seed_immediate_fact_before_v25(tmp_path)
    run_migrations(engine)
    service = ActionService(lambda: OntologyUnitOfWork(engine))
    with OntologyUnitOfWork(engine) as uow:
        job = uow.operator_decision.worker_job_for_source(
            job_kind="review_materialization",
            source_object_type="operator_review_eligibility_fact",
            source_object_id=fact_id,
        )
    assert job is not None
    return ReviewFixture(
        engine=engine,
        actions=OperatorReviewActions(service, shadow_token_signing_key=SIGNING_KEY),
        fact_id=fact_id,
        job_id=job.worker_job_id,
    )


def _claim_materialization(fixture: ReviewFixture, *, owner: str = "review-worker"):
    with OntologyUnitOfWork(fixture.engine) as uow:
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="review_materialization",
            lease_owner=owner,
            as_of=(AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(AT + timedelta(minutes=7)).isoformat(),
            limit=1,
        )
    assert len(claimed) == 1
    return claimed[0]


def _materialize_request(
    fixture: ReviewFixture,
    *,
    role: ActorRole = ActorRole.DETERMINISTIC_SYSTEM,
    owner: str = "review-worker",
) -> MaterializeOperatorReviewItemRequest:
    return MaterializeOperatorReviewItemRequest(
        review_eligibility_fact_id=fixture.fact_id,
        worker_job_id=fixture.job_id,
        lease_owner=owner,
        actor_id="system:operator-review",
        actor_role=role,
        requested_at=AT + timedelta(minutes=3),
    )


def _materialized_review(tmp_path: Path) -> tuple[ReviewFixture, str]:
    fixture = _review_fixture(tmp_path)
    _claim_materialization(fixture)
    outcome = fixture.actions.materialize_operator_review_item(
        _materialize_request(fixture)
    )
    review_id = next(
        ref.object_id
        for ref in outcome.result_refs
        if ref.object_type == "operator_review_item"
    )
    return fixture, review_id


def _register_metric(fixture: ReviewFixture, metric_key: str) -> None:
    scoreboard = ScoreboardActions(ActionService(lambda: OntologyUnitOfWork(fixture.engine)))
    outcome = scoreboard.record_observation(
        RecordScoreboardObservationRequest(
            group_key="review-tests",
            metric_key=metric_key,
            tally="0/0",
            detail="Registers the governed metric for review tests.",
            status="active",
            numerator=0.0,
            denominator=0.0,
            value=None,
            unit="ratio",
            evidence_refs=[ObjectRef("operator_review_fixture", fixture.fact_id)],
            effective_at=AT,
            supersedes_observation_id=None,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"review-tests:register:{metric_key}",
            requested_at=AT + timedelta(minutes=3),
        )
    )
    assert outcome.status is ActionStatus.COMMITTED


def _disposition_request(
    review_id: str,
    *,
    disposition: str = "effect_required",
    metric_keys: tuple[str, ...] = ("metric-a",),
    reason: str = "This review changes one governed scoreboard metric.",
    expected: str | None = None,
    key: str = "review-tests:disposition:1",
    role: ActorRole = ActorRole.JUDGE_OPERATOR,
) -> RecordScoreboardEffectDispositionRequest:
    return RecordScoreboardEffectDispositionRequest(
        review_id=review_id,
        expected_disposition_revision_id=expected,
        disposition=disposition,
        required_metric_keys=metric_keys,
        reason=reason,
        pre_update_legacy_sha256="a" * 64,
        actor_id="jun",
        actor_role=role,
        idempotency_key=key,
        requested_at=AT + timedelta(minutes=4),
    )


def test_immediate_review_materialization_is_system_only_and_idempotent(
    tmp_path: Path,
) -> None:
    fixture = _review_fixture(tmp_path)
    _claim_materialization(fixture)
    denied = fixture.actions.materialize_operator_review_item(
        _materialize_request(fixture, role=ActorRole.JUDGE_OPERATOR)
    )
    assert denied.status is ActionStatus.REJECTED

    request = _materialize_request(fixture)
    first = fixture.actions.materialize_operator_review_item(request)
    replay = fixture.actions.materialize_operator_review_item(request)

    assert first.status is ActionStatus.COMMITTED
    assert replay == first
    review_id = first.result_refs[0].object_id
    with OntologyUnitOfWork(fixture.engine) as uow:
        review = uow.operator_review.review_item(review_id)
        jobs = uow.operator_review.materialization_jobs_for_fact(fixture.fact_id)
    with fixture.engine.connect() as connection:
        action = connection.execute(
            text(
                "SELECT actor_role, idempotency_key FROM actions "
                "WHERE action_id = :action_id"
            ),
            {"action_id": first.action_id},
        ).one()
    assert review is not None
    assert review.review_eligibility_fact_id == fixture.fact_id
    assert review.review_kind == "operational_data_availability"
    assert review.outcome_revision_ids == ()
    assert review.lane == "jczq"
    assert review.business_key == "2026-09-04"
    assert action is not None
    assert action.actor_role == ActorRole.DETERMINISTIC_SYSTEM.value
    assert fixture.fact_id in action.idempotency_key
    assert len(jobs) == 1
    assert jobs[0].state == "completed"


def test_settlement_review_materializes_with_exact_result_scope(tmp_path: Path) -> None:
    settlement_actions, engine, result_set = _placed_result_set(tmp_path)
    requested = settlement_actions.request_settlement(_settlement_request(result_set))
    with OntologyUnitOfWork(engine) as uow:
        settlement_job = uow.operator_decision.claim_worker_jobs(
            job_kind="task_settlement",
            lease_owner="settlement-worker",
            as_of=(RESULT_AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(RESULT_AT + timedelta(minutes=7)).isoformat(),
            limit=1,
        )[0]
    settled = settlement_actions.settle_task(
        SettleTaskRequest(
            settlement_request_id=requested.result_refs[0].object_id,
            worker_job_id=settlement_job.worker_job_id,
            lease_owner="settlement-worker",
            settlement_method_version="operator-task-settlement-v1",
            rounding_policy_version="cn_sporttery_jczq_v1",
            actor_id="system:settlement",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            idempotency_key="review-tests:settlement",
            requested_at=RESULT_AT + timedelta(minutes=2),
        )
    )
    with engine.connect() as connection:
        fact_id = str(
            connection.scalar(
                select(
                    sor.operator_review_eligibility_facts.c.review_eligibility_fact_id
                ).where(
                    sor.operator_review_eligibility_facts.c.action_id
                    == settled.action_id
                )
            )
        )
    with OntologyUnitOfWork(engine) as uow:
        review_job = uow.operator_decision.claim_worker_jobs(
            job_kind="review_materialization",
            lease_owner="review-worker",
            as_of=(RESULT_AT + timedelta(minutes=3)).isoformat(),
            lease_expires_at=(RESULT_AT + timedelta(minutes=8)).isoformat(),
            limit=1,
        )[0]

    review_actions = OperatorReviewActions(
        ActionService(lambda: OntologyUnitOfWork(engine)),
        shadow_token_signing_key=SIGNING_KEY,
    )
    materialized = review_actions.materialize_operator_review_item(
        MaterializeOperatorReviewItemRequest(
            review_eligibility_fact_id=fact_id,
            worker_job_id=review_job.worker_job_id,
            lease_owner="review-worker",
            actor_id="system:operator-review",
            actor_role=ActorRole.DETERMINISTIC_SYSTEM,
            requested_at=RESULT_AT + timedelta(minutes=4),
        )
    )

    assert materialized.status is ActionStatus.COMMITTED
    review_id = next(
        ref.object_id
        for ref in materialized.result_refs
        if ref.object_type == "operator_review_item"
    )
    with OntologyUnitOfWork(engine) as uow:
        review = uow.operator_review.review_item(review_id)
    assert review is not None
    assert review.lane == "jczq"
    assert review.business_key == "2026-09-04"
    assert review.review_kind == "forecast_truth"
    assert review.market_prior_baseline_revision_id is not None
    assert len(review.outcome_revision_ids) == 1


def _seed_bound_outcome(engine) -> str:
    with engine.begin() as connection:
        context = connection.execute(
            text(
                "SELECT baseline.task_family_id, baseline.work_item_id, "
                "baseline.task_snapshot_hash, baseline.slate_revision_id, "
                "slate.lane, slate.business_key, probability.match_id, "
                "probability.official_offer_revision_id "
                "FROM operator_market_prior_baseline_revisions AS baseline "
                "JOIN operator_market_prior_baseline_probabilities AS probability "
                "ON probability.market_prior_baseline_revision_id = "
                "baseline.market_prior_baseline_revision_id "
                "JOIN official_sale_slate_revisions AS slate "
                "ON slate.slate_revision_id = baseline.slate_revision_id LIMIT 1"
            )
        ).one()
        connection.execute(
            text(
                "INSERT INTO actions (action_id, action_type, actor_id, actor_role, "
                "requested_at, idempotency_key, request_hash, expected_versions_json, "
                "payload_json, policy_version, status, result_refs_json) VALUES "
                "('ACT-result-review', 'import_result_evidence_set', 'system:result', "
                "'deterministic_system', :at, 'review-tests:result', 'request-hash', "
                "'{}', '{}', 'governance-v1', 'accepted', '[]')"
            ),
            {"at": (AT + timedelta(minutes=5)).isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO operator_result_set_families "
                "(result_set_family_id, task_family_id, lane, business_key, created_at) "
                "VALUES ('result-family-review', :task, :lane, :business, :at)"
            ),
            {
                "task": context.task_family_id,
                "lane": context.lane,
                "business": context.business_key,
                "at": (AT + timedelta(minutes=5)).isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO operator_result_set_revisions "
                "(result_set_revision_id, result_set_family_id, revision_no, "
                "supersedes_revision_id, task_family_id, work_item_id, lane, business_key, "
                "task_snapshot_hash, slate_revision_id, result_cutoff_at, importer_version, "
                "zucai_prize_table_revision_id, match_count, source_receipt_count, "
                "outcome_count, content_hash, action_id, created_at) VALUES "
                "('result-set-review', 'result-family-review', 1, NULL, :task, :work, "
                ":lane, :business, :snapshot, :slate, :at, 'review-test-v1', NULL, "
                "1, 3, 1, :hash, 'ACT-result-review', :at)"
            ),
            {
                "task": context.task_family_id,
                "work": context.work_item_id,
                "lane": context.lane,
                "business": context.business_key,
                "snapshot": context.task_snapshot_hash,
                "slate": context.slate_revision_id,
                "at": (AT + timedelta(minutes=5)).isoformat(),
                "hash": "b" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO operator_result_match_revisions "
                "(match_result_revision_id, result_set_revision_id, match_index, "
                "official_match_no, official_offer_revision_id, match_id, "
                "normalized_disposition, normalized_home_90, normalized_away_90, "
                "agreement_state) VALUES ('match-result-review', 'result-set-review', 0, "
                "'001', :offer, :match, 'played_90', 2, 1, 'agreed')"
            ),
            {"offer": context.official_offer_revision_id, "match": context.match_id},
        )
        connection.execute(
            text(
                "INSERT INTO operator_result_source_receipts "
                "(result_source_receipt_id, match_result_revision_id, source_index, "
                "source_kind, source_artifact_retrieval_id, captured_at, "
                "source_disposition, home_90, away_90, receipt_state, invalid_code) "
                "VALUES (:id, 'match-result-review', :idx, :kind, 'retrieval-1', :at, "
                "'played_90', 2, 1, 'available', NULL)"
            ),
            [
                {
                    "id": f"result-source-review-{index}",
                    "idx": index,
                    "kind": kind,
                    "at": (AT + timedelta(minutes=5)).isoformat(),
                }
                for index, kind in enumerate(
                    ("api_football", "sporttery_game90", "okooo_manual")
                )
            ],
        )
        connection.execute(
            text(
                "INSERT INTO operator_outcome_revisions "
                "(outcome_revision_id, outcome_family_id, revision_no, "
                "supersedes_revision_id, outcome_index, match_id, "
                "match_result_revision_id, result_set_revision_id, result_disposition, "
                "home_90, away_90, source_artifact_retrieval_ids_json, recorded_at, "
                "action_id) VALUES ('outcome-review-1', 'outcome-family-review', 1, NULL, "
                "0, :match, 'match-result-review', 'result-set-review', 'played_90', "
                "2, 1, '[\"retrieval-1\"]', :at, 'ACT-result-review')"
            ),
            {"match": context.match_id, "at": (AT + timedelta(minutes=5)).isoformat()},
        )
        connection.execute(
            text(
                "UPDATE actions SET status = 'committed', committed_at = :at "
                "WHERE action_id = 'ACT-result-review'"
            ),
            {"at": (AT + timedelta(minutes=5)).isoformat()},
        )
    return "outcome-review-1"


def test_forecast_truth_review_waits_for_every_bound_outcome(tmp_path: Path) -> None:
    source = _no_ticket_fixture(tmp_path)
    closed = source.actions.record_no_ticket(
        _no_ticket_request(source, key="review-tests:forecast-no-ticket")
    )
    fact_id = next(
        ref.object_id
        for ref in closed.result_refs
        if ref.object_type == "operator_review_eligibility_fact"
    )
    with OntologyUnitOfWork(source.engine) as uow:
        job = uow.operator_decision.worker_job_for_source(
            job_kind="review_materialization",
            source_object_type="operator_review_eligibility_fact",
            source_object_id=fact_id,
        )
        claimed = uow.operator_decision.claim_worker_jobs(
            job_kind="review_materialization",
            lease_owner="review-worker",
            as_of=(NO_TICKET_AT + timedelta(minutes=2)).isoformat(),
            lease_expires_at=(NO_TICKET_AT + timedelta(minutes=8)).isoformat(),
            limit=1,
        )
    assert job is not None and len(claimed) == 1
    actions = OperatorReviewActions(
        ActionService(lambda: OntologyUnitOfWork(source.engine)),
        shadow_token_signing_key=SIGNING_KEY,
    )
    request = MaterializeOperatorReviewItemRequest(
        review_eligibility_fact_id=fact_id,
        worker_job_id=job.worker_job_id,
        lease_owner="review-worker",
        actor_id="system:operator-review",
        actor_role=ActorRole.DETERMINISTIC_SYSTEM,
        requested_at=NO_TICKET_AT + timedelta(minutes=3),
    )

    with pytest.raises(ReviewNotReadyError, match="Outcomes"):
        actions.materialize_operator_review_item(request)
    outcome_id = _seed_bound_outcome(source.engine)
    materialized = actions.materialize_operator_review_item(request)

    with OntologyUnitOfWork(source.engine) as uow:
        review = uow.operator_review.review_for_eligibility_fact(fact_id)
    assert materialized.status is ActionStatus.COMMITTED
    assert review is not None
    assert review.review_kind == "forecast_truth"
    assert review.outcome_revision_ids == (outcome_id,)


def test_disposition_validates_metric_sets_and_supersedes_only_before_completion(
    tmp_path: Path,
) -> None:
    fixture, review_id = _materialized_review(tmp_path)
    _register_metric(fixture, "metric-a")

    with pytest.raises(ValueError, match="non-empty"):
        _disposition_request(review_id, metric_keys=())
    with pytest.raises(ValueError, match="unique"):
        _disposition_request(review_id, metric_keys=("metric-a", "metric-a"))
    with pytest.raises(ValueError, match="reason"):
        _disposition_request(review_id, reason=" ")
    with pytest.raises(ValueError, match="no_effect.*metric"):
        _disposition_request(
            review_id,
            disposition="no_effect",
            metric_keys=("metric-a",),
        )
    with pytest.raises(ValueError, match="registered"):
        fixture.actions.record_scoreboard_effect_disposition(
            _disposition_request(
                review_id,
                metric_keys=("unknown-metric",),
                key="review-tests:disposition:unknown",
            )
        )

    first = fixture.actions.record_scoreboard_effect_disposition(
        _disposition_request(review_id)
    )
    first_id = first.result_refs[0].object_id
    with pytest.raises(OptimisticConcurrencyError, match="current disposition"):
        fixture.actions.record_scoreboard_effect_disposition(
            _disposition_request(
                review_id,
                expected="missing-revision",
                key="review-tests:disposition:stale",
            )
        )

    completed = fixture.actions.record_scoreboard_effect_disposition(
        _disposition_request(
            review_id,
            disposition="no_effect",
            metric_keys=(),
            reason="The review does not change any governed metric.",
            expected=first_id,
            key="review-tests:disposition:2",
        )
    )
    assert completed.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(fixture.engine) as uow:
        current = uow.operator_review.current_disposition(review_id)
        receipt = uow.operator_review.completion_receipt_for_review(review_id)
        links = uow.operator_review.observation_links_for_disposition(first_id)
    assert current is not None and current.revision_no == 2
    assert current.disposition == "no_effect"
    assert receipt is not None
    assert receipt.post_update_legacy_sha256 is None
    assert receipt.observation_action_ids == ()
    assert receipt.shadow_review_id is None
    assert links == ()

    with pytest.raises(ValueError, match="complete"):
        fixture.actions.record_scoreboard_effect_disposition(
            _disposition_request(
                review_id,
                disposition="no_effect",
                metric_keys=(),
                reason="A terminal review cannot be revised.",
                expected=current.disposition_revision_id,
                key="review-tests:disposition:terminal",
            )
        )


def test_no_effect_disposition_rolls_back_if_receipt_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, review_id = _materialized_review(tmp_path)
    original = OperatorReviewRepository.insert_completion_receipt

    def insert_then_fail(repository, row):
        original(repository, row)
        raise RuntimeError("injected receipt failure")

    monkeypatch.setattr(
        OperatorReviewRepository,
        "insert_completion_receipt",
        insert_then_fail,
    )
    with pytest.raises(RuntimeError, match="injected"):
        fixture.actions.record_scoreboard_effect_disposition(
            _disposition_request(
                review_id,
                disposition="no_effect",
                metric_keys=(),
                reason="There is no governed scoreboard effect.",
            )
        )

    with fixture.engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM operator_scoreboard_effect_disposition_revisions), "
                "(SELECT COUNT(*) FROM operator_scoreboard_review_completion_receipts)"
            )
        ).one()
    assert counts == (0, 0)
