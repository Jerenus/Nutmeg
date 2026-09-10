from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    RecordAdjudicationRequest,
    WorkflowActions,
)
from nutmeg.ontology.operator.review_actions import ShadowReviewTokenCodec
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.product.operator_contracts import ReviewStep
from nutmeg.product.operator_queries import OperatorQueryService
from nutmeg.product.operator_tokens import OperatorSnapshotTokenCodec
from tests.ontology.operator.test_judgment_actions import AT
from tests.ontology.operator.test_review_actions import _materialized_review
from tests.ontology.operator.test_review_completion import _effect_review
from tests.product.operator_v2.test_review_ui import _ProjectionReadyRepository

TOKEN_KEY = b"package-eleven-review-history-projection-key"


def _queries(fixture, tmp_path: Path, cutoff) -> OperatorQueryService:
    repository = _ProjectionReadyRepository(fixture.engine, tmp_path / "analytics.db")
    return OperatorQueryService(
        repository=repository,
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: cutoff,
        unit_of_work_factory=lambda: OntologyUnitOfWork(fixture.engine),
        snapshot_tokens=OperatorSnapshotTokenCodec(TOKEN_KEY),
        shadow_review_tokens=ShadowReviewTokenCodec(TOKEN_KEY),
    )


def test_review_projection_assembles_issue_adjudication_history(
    tmp_path: Path,
) -> None:
    fixture, _review_id = _materialized_review(tmp_path)
    workflow = WorkflowActions(
        ActionService(lambda: OntologyUnitOfWork(fixture.engine))
    )
    adjudicated_at = AT + timedelta(minutes=4)
    outcome = workflow.record_adjudication(
        RecordAdjudicationRequest(
            subject_type="issue",
            subject_id="2026-09-04",
            decision="approve",
            reason="采用本期已核对的结构。",
            evidence_rejected=[{"kind": "source", "ref": "fixture"}],
            alternative={},
            supersedes_adjudication_id=None,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key="review-history-projection:adjudication",
            requested_at=adjudicated_at,
        )
    )
    assert outcome.is_success
    cutoff = AT + timedelta(days=1)
    task = _queries(fixture, tmp_path, cutoff).task(
        "jczq:2026-09-04",
        as_of=cutoff,
    )

    assert isinstance(task.step, ReviewStep)
    assert [item.decision for item in task.step.adjudication_history] == ["approve"]
    assert task.step.adjudication_history[0].reason == "采用本期已核对的结构。"


def test_review_projection_assembles_linked_scoreboard_observation_history(
    tmp_path: Path,
) -> None:
    fixture, _review_id, _disposition_id, _observation_id, _action_id = (
        _effect_review(tmp_path)
    )
    cutoff = AT + timedelta(days=1)

    task = _queries(fixture, tmp_path, cutoff).task(
        "jczq:2026-09-04",
        as_of=cutoff,
    )

    assert isinstance(task.step, ReviewStep)
    assert len(task.step.scoreboard_observation_history) == 1
    observation = task.step.scoreboard_observation_history[0]
    assert observation.metric_key == "metric-a"
    assert observation.tally == "1/1"
    assert observation.value_decimal == "1.0"
    assert observation.effective_at == AT + timedelta(minutes=5)
