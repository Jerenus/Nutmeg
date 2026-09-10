from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.product.operator_contracts import OperatorLane, OperatorTaskState

_FAR_FUTURE = datetime.max.replace(tzinfo=UTC)

STATE_LABELS: dict[OperatorTaskState, str] = {
    OperatorTaskState.WAITING_DATA: "等待数据",
    OperatorTaskState.PREPARE: "准备数据",
    OperatorTaskState.JUDGE_MATCHES: "逐项裁决",
    OperatorTaskState.CONSTRUCT_TICKET: "比较票版",
    OperatorTaskState.AUDIT_DEPLOYMENT: "审计部署",
    OperatorTaskState.AWAIT_CONFIRMATION: "等待确认",
    OperatorTaskState.AWAIT_LEDGER: "等待入账",
    OperatorTaskState.AWAIT_RESULT: "等待赛果",
    OperatorTaskState.REVIEW: "复盘",
    OperatorTaskState.COMPLETE: "已完成",
    OperatorTaskState.BLOCKED: "需要修复",
}

NEXT_ACTION_LABELS: dict[OperatorTaskState, str] = {
    OperatorTaskState.WAITING_DATA: "查看等待原因",
    OperatorTaskState.PREPARE: "准备本期数据",
    OperatorTaskState.JUDGE_MATCHES: "继续裁决",
    OperatorTaskState.CONSTRUCT_TICKET: "比较候选票",
    OperatorTaskState.AUDIT_DEPLOYMENT: "检查审计与部署门",
    OperatorTaskState.AWAIT_CONFIRMATION: "完成出票确认",
    OperatorTaskState.AWAIT_LEDGER: "确认实际入账",
    OperatorTaskState.AWAIT_RESULT: "查看赛果状态",
    OperatorTaskState.REVIEW: "继续复盘",
    OperatorTaskState.COMPLETE: "查看摘要",
    OperatorTaskState.BLOCKED: "查看恢复步骤",
}


@dataclass(frozen=True, slots=True)
class OperatorTaskFacts:
    lane: OperatorLane
    business_key: str
    deadline_at: datetime | None
    waiting_until: datetime | None
    source_error_code: str | None
    has_issue: bool
    has_prep: bool
    unresolved_adjudications: int
    candidate_count: int
    selected_candidate_id: str | None
    audit_recorded: bool
    deployment_decision: str | None
    ticket_artifact_id: str | None
    confirmation_state: str | None
    placement_state: str | None
    result_available: bool
    pending_review_items: int


def resolve_state(facts: OperatorTaskFacts) -> OperatorTaskState:
    if facts.source_error_code:
        return OperatorTaskState.BLOCKED
    if not facts.has_issue:
        return OperatorTaskState.WAITING_DATA
    if not facts.has_prep:
        return OperatorTaskState.PREPARE
    if facts.unresolved_adjudications:
        return OperatorTaskState.JUDGE_MATCHES
    if facts.result_available and facts.pending_review_items:
        return OperatorTaskState.REVIEW
    if not facts.candidate_count or facts.selected_candidate_id is None:
        return OperatorTaskState.CONSTRUCT_TICKET
    if not facts.audit_recorded:
        return OperatorTaskState.AUDIT_DEPLOYMENT
    if facts.deployment_decision in {"change_structure", "drop_match"}:
        return OperatorTaskState.CONSTRUCT_TICKET
    if facts.deployment_decision == "empty_position":
        return OperatorTaskState.COMPLETE
    if facts.deployment_decision != "keep":
        return OperatorTaskState.AUDIT_DEPLOYMENT
    if facts.ticket_artifact_id is None:
        return OperatorTaskState.BLOCKED
    if facts.placement_state == "shadow":
        return OperatorTaskState.COMPLETE
    if facts.confirmation_state in {None, "not_issued", "open", "expired"}:
        return OperatorTaskState.AWAIT_CONFIRMATION
    if facts.placement_state != "placed":
        return OperatorTaskState.AWAIT_LEDGER
    if not facts.result_available:
        return OperatorTaskState.AWAIT_RESULT
    return OperatorTaskState.COMPLETE


def is_passive_expired_deployment(
    facts: OperatorTaskFacts,
    now: datetime,
) -> bool:
    return bool(
        facts.deadline_at is not None
        and facts.deadline_at <= now
        and resolve_state(facts)
        in {
            OperatorTaskState.WAITING_DATA,
            OperatorTaskState.PREPARE,
            OperatorTaskState.JUDGE_MATCHES,
            OperatorTaskState.CONSTRUCT_TICKET,
            OperatorTaskState.AUDIT_DEPLOYMENT,
        }
    )


def priority_key(facts: OperatorTaskFacts, now: datetime) -> tuple[int, datetime, str, str, str]:
    state = resolve_state(facts)
    deadline = facts.deadline_at or _FAR_FUTURE
    before_deadline_human = state in {
        OperatorTaskState.JUDGE_MATCHES,
        OperatorTaskState.CONSTRUCT_TICKET,
        OperatorTaskState.AUDIT_DEPLOYMENT,
        OperatorTaskState.AWAIT_CONFIRMATION,
    } and (facts.deadline_at is None or facts.deadline_at > now)
    overdue_resolution = (
        facts.deadline_at is not None
        and facts.deadline_at <= now
        and state
        in {
            OperatorTaskState.AWAIT_CONFIRMATION,
            OperatorTaskState.AWAIT_LEDGER,
            OperatorTaskState.BLOCKED,
        }
    )
    if before_deadline_human:
        category = 0
    elif overdue_resolution:
        category = 1
    elif state not in {
        OperatorTaskState.WAITING_DATA,
        OperatorTaskState.REVIEW,
        OperatorTaskState.COMPLETE,
    }:
        category = 2
    elif state is OperatorTaskState.REVIEW:
        category = 3
    elif state is OperatorTaskState.WAITING_DATA:
        category = 4
    else:
        category = 5
    next_time = (
        facts.waiting_until or _FAR_FUTURE
        if state is OperatorTaskState.WAITING_DATA
        else deadline
    )
    task_id = f"{facts.lane.value}:{facts.business_key}"
    return (category, next_time, facts.lane.value, facts.business_key, task_id)
