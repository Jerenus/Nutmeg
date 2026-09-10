from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.actions.workflow_actions import (
    RecordAdjudicationRequest,
    WorkflowActions,
)
from nutmeg.ontology.operator.decision_actions import (
    FaceOffsetInput,
    FaceProbabilityInput,
    FactorAdjustmentInput,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.ontology.operator.test_judgment_actions import (
    AT,
    _create_baseline_and_envelope,
    _judgment_request,
)
from tests.ontology.operator.test_judgment_actions import (
    _fixture as _judgment_fixture,
)
from tests.ontology.operator.test_review_actions import _materialized_review
from tests.ontology.operator.test_review_completion import _effect_review


def _record_issue_adjudication(
    fixture,
    *,
    subject_id: str,
    decision: str,
    reason: str,
    requested_at,
    key: str,
) -> None:
    workflow = WorkflowActions(ActionService(lambda: OntologyUnitOfWork(fixture.engine)))
    workflow.record_adjudication(
        RecordAdjudicationRequest(
            subject_type="issue",
            subject_id=subject_id,
            decision=decision,
            reason=reason,
            evidence_rejected=[{"kind": "source", "ref": "fixture"}],
            alternative={"internal": "must-not-leak"},
            supersedes_adjudication_id=None,
            actor_id="jun",
            actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=key,
            requested_at=requested_at,
        )
    )


def test_review_adjudication_history_is_issue_scoped_temporal_and_business_only(
    tmp_path: Path,
) -> None:
    fixture, _review_id = _materialized_review(tmp_path)
    _record_issue_adjudication(
        fixture,
        subject_id="2026-09-04",
        decision="approve",
        reason="采用本期已核对的结构。",
        requested_at=AT + timedelta(minutes=4),
        key="review-history:relevant",
    )
    _record_issue_adjudication(
        fixture,
        subject_id="2026-09-05",
        decision="override",
        reason="另一任务的裁决。",
        requested_at=AT + timedelta(minutes=5),
        key="review-history:other-task",
    )
    _record_issue_adjudication(
        fixture,
        subject_id="2026-09-04",
        decision="override",
        reason="截止时间之后的裁决。",
        requested_at=AT + timedelta(minutes=7),
        key="review-history:future",
    )

    with OntologyUnitOfWork(fixture.engine) as uow:
        history = uow.operator_review.adjudication_history(
            business_key="2026-09-04",
            as_of=(AT + timedelta(minutes=6)).isoformat(),
        )

    assert [(row.decision, row.reason, row.rejected_evidence_count) for row in history] == [
        ("approve", "采用本期已核对的结构。", 1)
    ]
    assert history[0].created_at == (AT + timedelta(minutes=4)).isoformat()
    assert not hasattr(history[0], "adjudication_id")
    assert not hasattr(history[0], "actor_id")
    assert not hasattr(history[0], "alternative")


def test_review_scoreboard_observation_history_joins_visible_business_facts_only(
    tmp_path: Path,
) -> None:
    fixture, _review_id, disposition_id, _observation_id, _action_id = _effect_review(
        tmp_path
    )

    with OntologyUnitOfWork(fixture.engine) as uow:
        history = uow.operator_review.scoreboard_observation_history(disposition_id)

    assert len(history) == 1
    row = history[0]
    assert row.metric_key == "metric-a"
    assert row.tally == "1/1"
    assert row.detail == "The externally governed scoreboard update is now observed."
    assert row.status == "active"
    assert row.numerator == 1.0
    assert row.denominator == 1.0
    assert row.value == 1.0
    assert row.unit == "ratio"
    assert row.effective_at == (AT + timedelta(minutes=5)).isoformat()
    assert not hasattr(row, "scoreboard_observation_id")
    assert not hasattr(row, "observation_action_id")
    assert not hasattr(row, "observed_legacy_sha256")


def test_review_factor_ids_are_limited_to_families_used_by_the_task(
    tmp_path: Path,
) -> None:
    fixture = _judgment_fixture(tmp_path)
    baseline_id, envelope_id = _create_baseline_and_envelope(fixture)
    fixture.decision_actions.commit_operator_match_judgment(
        _judgment_request(
            fixture,
            baseline_id,
            envelope_id,
            factors=(
                FactorAdjustmentInput(
                    factor_definition_id="factor-1",
                    scope_key="match-1",
                    evidence_ref_tokens=("obs-anchor",),
                    offsets=(
                        FaceOffsetInput("3", "0.010000000000"),
                        FaceOffsetInput("1", "-0.005000000000"),
                        FaceOffsetInput("0", "-0.005000000000"),
                    ),
                ),
            ),
            belief=(
                FaceProbabilityInput("3", "0.410000000000"),
                FaceProbabilityInput("1", "0.295000000000"),
                FaceProbabilityInput("0", "0.295000000000"),
            ),
        )
    )

    with OntologyUnitOfWork(fixture.engine) as uow:
        factor_ids = uow.operator_review.factor_ids_for_task(
            "jczq:2026-09-04",
            as_of=(AT + timedelta(minutes=1)).isoformat(),
        )

    assert factor_ids == ("factor-family-1",)
