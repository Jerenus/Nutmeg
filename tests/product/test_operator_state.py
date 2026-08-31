from dataclasses import replace
from datetime import UTC, datetime

import pytest

from nutmeg.product.operator_contracts import OperatorLane, OperatorTaskState
from nutmeg.product.operator_state import (
    NEXT_ACTION_LABELS,
    STATE_LABELS,
    OperatorTaskFacts,
    priority_key,
    resolve_state,
)

NOW = datetime(2026, 8, 28, 10, tzinfo=UTC)


def _facts(**changes) -> OperatorTaskFacts:
    base = OperatorTaskFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26112",
        deadline_at=datetime(2026, 8, 29, 3, tzinfo=UTC),
        waiting_until=None,
        source_error_code=None,
        has_issue=True,
        has_prep=True,
        unresolved_adjudications=1,
        candidate_count=1,
        selected_candidate_id=None,
        audit_recorded=False,
        deployment_decision=None,
        ticket_artifact_id=None,
        confirmation_state=None,
        placement_state=None,
        result_available=False,
        pending_review_items=0,
    )
    return replace(base, **changes)


def test_zucai_state_advances_only_from_persisted_facts() -> None:
    assert resolve_state(_facts()) is OperatorTaskState.JUDGE_MATCHES
    assert resolve_state(_facts(unresolved_adjudications=0)) is OperatorTaskState.CONSTRUCT_TICKET
    assert (
        resolve_state(_facts(unresolved_adjudications=0, selected_candidate_id="R432"))
        is OperatorTaskState.AUDIT_DEPLOYMENT
    )
    assert (
        resolve_state(
            _facts(
                unresolved_adjudications=0,
                selected_candidate_id="R432",
                audit_recorded=True,
                deployment_decision="keep",
                ticket_artifact_id="tat-1",
                confirmation_state="not_issued",
            )
        )
        is OperatorTaskState.AWAIT_CONFIRMATION
    )
    assert (
        resolve_state(
            _facts(
                unresolved_adjudications=0,
                selected_candidate_id="R432",
                audit_recorded=True,
                deployment_decision="keep",
                ticket_artifact_id="tat-1",
                confirmation_state="consumed",
                placement_state="placed",
            )
        )
        is OperatorTaskState.AWAIT_RESULT
    )
    assert (
        resolve_state(
            _facts(
                unresolved_adjudications=0,
                selected_candidate_id="R432",
                audit_recorded=True,
                deployment_decision="keep",
                ticket_artifact_id="tat-1",
                confirmation_state="consumed",
                placement_state="placed",
                result_available=True,
                pending_review_items=2,
            )
        )
        is OperatorTaskState.REVIEW
    )


def test_priority_uses_workflow_and_deadline_not_football_values() -> None:
    due = _facts()
    unknown_deadline = replace(due, business_key="26113", deadline_at=None)
    review = _facts(
        business_key="26111",
        result_available=True,
        pending_review_items=1,
        unresolved_adjudications=0,
        selected_candidate_id="R432",
        audit_recorded=True,
        deployment_decision="keep",
        ticket_artifact_id="tat-1",
        confirmation_state="consumed",
        placement_state="placed",
    )

    assert priority_key(due, NOW) < priority_key(unknown_deadline, NOW)
    assert priority_key(due, NOW) < priority_key(review, NOW)


def test_waiting_tasks_sort_by_retry_time_before_deadline() -> None:
    early_retry = _facts(
        has_issue=False,
        waiting_until=datetime(2026, 8, 28, 11, tzinfo=UTC),
        deadline_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    early_deadline = replace(
        early_retry,
        business_key="26113",
        waiting_until=datetime(2026, 8, 28, 12, tzinfo=UTC),
        deadline_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert priority_key(early_retry, NOW) < priority_key(early_deadline, NOW)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"has_issue": False}, OperatorTaskState.WAITING_DATA),
        ({"has_prep": False}, OperatorTaskState.PREPARE),
        ({"source_error_code": "invalid"}, OperatorTaskState.BLOCKED),
        (
            {"unresolved_adjudications": 0, "candidate_count": 0},
            OperatorTaskState.CONSTRUCT_TICKET,
        ),
        (
            {
                "unresolved_adjudications": 0,
                "selected_candidate_id": "R432",
                "audit_recorded": True,
                "deployment_decision": "keep",
                "ticket_artifact_id": "tat-1",
                "confirmation_state": "consumed",
                "placement_state": "shadow",
            },
            OperatorTaskState.COMPLETE,
        ),
        (
            {
                "unresolved_adjudications": 0,
                "selected_candidate_id": "R432",
                "audit_recorded": True,
                "deployment_decision": "change_structure",
            },
            OperatorTaskState.CONSTRUCT_TICKET,
        ),
        (
            {
                "unresolved_adjudications": 0,
                "selected_candidate_id": "R432",
                "audit_recorded": True,
                "deployment_decision": "drop_match",
            },
            OperatorTaskState.CONSTRUCT_TICKET,
        ),
        (
            {
                "unresolved_adjudications": 0,
                "selected_candidate_id": "R432",
                "audit_recorded": True,
                "deployment_decision": "empty_position",
            },
            OperatorTaskState.COMPLETE,
        ),
    ],
)
def test_transition_table(changes, expected) -> None:
    assert resolve_state(_facts(**changes)) is expected


def test_priority_ties_break_by_lane_then_business_key() -> None:
    zucai = _facts(business_key="26112")
    jczq_later = replace(zucai, lane=OperatorLane.JCZQ, business_key="20260829")
    jczq_earlier = replace(jczq_later, business_key="20260828")

    assert priority_key(jczq_earlier, NOW) < priority_key(jczq_later, NOW)
    assert priority_key(jczq_later, NOW) < priority_key(zucai, NOW)


def test_complete_tasks_sort_after_waiting_tasks() -> None:
    waiting = _facts(has_issue=False)
    complete = _facts(
        unresolved_adjudications=0,
        selected_candidate_id="R432",
        audit_recorded=True,
        deployment_decision="empty_position",
    )

    assert priority_key(waiting, NOW) < priority_key(complete, NOW)


def test_state_and_action_labels_cover_every_state() -> None:
    assert set(STATE_LABELS) == set(OperatorTaskState)
    assert set(NEXT_ACTION_LABELS) == set(OperatorTaskState)
    assert all(STATE_LABELS.values())
    assert all(NEXT_ACTION_LABELS.values())
