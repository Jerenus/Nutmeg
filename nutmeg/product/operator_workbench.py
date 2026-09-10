"""Deterministic v2 operator workbench read-model assembly."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from nutmeg.product.errors import ProductNotFoundError
from nutmeg.product.operator_contracts import (
    AwaitResultStep,
    LaneScheduleRecoveryViewV1,
    OfferMarketViewV1,
    OfficialOfferViewV1,
    OfficialSaleSlateViewV1,
    OperatorBlockViewV1,
    OperatorLane,
    OperatorLaneResponseV1,
    OperatorTaskDetailV1,
    OperatorTaskState,
    OperatorTaskSummaryV1,
    OperatorTodayResponseV1,
    OperatorWorkItemViewV1,
    TodayWorkItemViewV1,
    WorkItemActionViewV1,
    WorkItemProgressViewV1,
)
from nutmeg.product.operator_lanes import (
    DiscoveryTask,
    SaleSlateSnapshot,
    SaleTaskState,
    ScheduleRecoverySnapshot,
    ScopeKind,
    TodayPriorityFacts,
    focus_business_key,
    offer_state,
    task_state,
    today_priority_key,
)
from nutmeg.product.operator_recovery import (
    OPERATOR_RECOVERY_CATALOG,
    recovery_block_for_step,
)
from nutmeg.product.operator_state import (
    OperatorTaskFacts,
    is_passive_expired_deployment,
    resolve_state,
)

_PHASE_BY_STATE = {
    OperatorTaskState.WAITING_DATA: "prepare_evidence",
    OperatorTaskState.PREPARE: "prepare_evidence",
    OperatorTaskState.JUDGE_MATCHES: "judge_matches",
    OperatorTaskState.CONSTRUCT_TICKET: "compare_tickets",
    OperatorTaskState.AUDIT_DEPLOYMENT: "audit_deployment",
    OperatorTaskState.AWAIT_CONFIRMATION: "await_confirmation",
    OperatorTaskState.AWAIT_LEDGER: "blocked",
    OperatorTaskState.AWAIT_RESULT: "await_result",
    OperatorTaskState.REVIEW: "review",
    OperatorTaskState.COMPLETE: "complete",
    OperatorTaskState.BLOCKED: "blocked",
}

_ACTION_LABELS = {
    "prepare_evidence": "补齐并冻结证据",
    "judge_matches": "继续逐场裁决",
    "compare_tickets": "比较候选票",
    "audit_deployment": "审计并确认票版",
    "await_confirmation": "查看 Telegram 出票确认",
    "await_result": "检查赛果与结算状态",
    "review": "继续复盘",
    "blocked": "查看恢复步骤",
}

_MARKET_LABELS = {
    "had": "胜平负",
    "hhad": "让球胜平负",
    "ttg": "总进球",
    "crs": "比分",
}


class ProgressViewSource(Protocol):
    completed: int
    total: int
    label: str


class BuiltTaskViewSource(Protocol):
    facts: OperatorTaskFacts
    progress: ProgressViewSource
    step: object
    mutation_token: str
    work_item_identity: str | None
    scope_kind: ScopeKind | None
    projected_state: OperatorTaskState | None
    deployment_outcome: str | None
    scope_label: str | None


class MatchViewSource(Protocol):
    home_team: str | None
    away_team: str | None
    competition: str | None
    scheduled_at: datetime | str


MatchLookup = Callable[[str, str], MatchViewSource | None]
EvidenceCountLookup = Callable[[str], tuple[int, int]]


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _datetime(value: object, label: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return _aware(parsed, label)


def _scope_for_state(state: OperatorTaskState, facts: OperatorTaskFacts) -> ScopeKind:
    if state is OperatorTaskState.REVIEW:
        return ScopeKind.REVIEW
    if state is OperatorTaskState.AWAIT_RESULT:
        return ScopeKind.TICKET
    if state in {OperatorTaskState.AWAIT_CONFIRMATION, OperatorTaskState.AWAIT_LEDGER}:
        return ScopeKind.ARTIFACT
    if state is OperatorTaskState.BLOCKED and facts.ticket_artifact_id is not None:
        return ScopeKind.ARTIFACT
    return ScopeKind.SALE_WAVE


def _deployment_outcome(scope: ScopeKind, facts: OperatorTaskFacts) -> str | None:
    if scope in {ScopeKind.TICKET, ScopeKind.REVIEW}:
        return None
    if facts.deployment_decision == "empty_position":
        return "no_ticket"
    if facts.placement_state == "placed":
        return "placed"
    if facts.placement_state == "shadow":
        return "expired"
    return "pending"


def _deployment_outcome_for_built(
    built: BuiltTaskViewSource,
    scope: ScopeKind,
) -> str | None:
    explicit = getattr(built, "deployment_outcome", None)
    return explicit if explicit is not None else _deployment_outcome(scope, built.facts)


def _block_for_state(
    state: OperatorTaskState,
    facts: OperatorTaskFacts,
    step: object,
    *,
    recovery_link: str,
) -> OperatorBlockViewV1 | None:
    fallback_code = None
    if state is OperatorTaskState.WAITING_DATA:
        fallback_code = "evidence_missing"
    elif state is OperatorTaskState.AWAIT_LEDGER:
        fallback_code = "placement_ledger_integrity"
    elif state is OperatorTaskState.BLOCKED:
        fallback_code = facts.source_error_code or "operator_task_blocked"
    return recovery_block_for_step(
        step,
        recovery_link=recovery_link,
        reevaluate_at=facts.waiting_until,
        fallback_code=fallback_code,
    )


def _task_label(lane: OperatorLane, business_key: str) -> str:
    return (
        f"胜负彩 {business_key} 期"
        if lane is OperatorLane.ZUCAI
        else f"竞彩 {business_key}"
    )


def _scope_label(scope: ScopeKind, lane: OperatorLane) -> str:
    labels = {
        ScopeKind.SALE_WAVE: "本期 14 场" if lane is OperatorLane.ZUCAI else "当前在售场次",
        ScopeKind.ARTIFACT: "已审计票版",
        ScopeKind.TICKET: "已出票票据",
        ScopeKind.REVIEW: "赛后复盘",
    }
    return labels[scope]


def operator_work_item_key(scope: ScopeKind, identity: str) -> str:
    digest = hashlib.sha256(
        f"{scope.value}:{identity}".encode("utf-8")
    ).hexdigest()[:20]
    return f"{scope.value.replace('_', '-')}-{digest}"


def _work_item_key(built: BuiltTaskViewSource, scope: ScopeKind) -> str:
    identity = getattr(built, "work_item_identity", None) or built.mutation_token
    return operator_work_item_key(scope, identity)


def _state_for_built(built: BuiltTaskViewSource) -> OperatorTaskState:
    return getattr(built, "projected_state", None) or resolve_state(built.facts)


def _scope_for_built(
    built: BuiltTaskViewSource,
    state: OperatorTaskState,
) -> ScopeKind:
    return getattr(built, "scope_kind", None) or _scope_for_state(state, built.facts)


def schedule_recovery_views(
    snapshots: Sequence[ScheduleRecoverySnapshot],
) -> tuple[LaneScheduleRecoveryViewV1, ...]:
    successful = {"slate_imported", "confirmed_no_sale"}
    recoveries = []
    for snapshot in snapshots:
        if snapshot.last_check_state in successful:
            continue
        recovery_link = "/operator-next/maintenance"
        message = (
            "今日官方赛程尚未完成检查。"
            if snapshot.last_check_state is None
            else "今日官方赛程检查失败。"
        )
        recoveries.append(
            LaneScheduleRecoveryViewV1(
                lane=snapshot.lane,
                shanghai_check_date=snapshot.shanghai_check_date,
                recovery_key=(
                    f"{snapshot.lane.value}:{snapshot.shanghai_check_date}:schedule"
                ),
                last_check_state=snapshot.last_check_state,
                last_checked_at=snapshot.last_checked_at,
                last_source_run_state=snapshot.last_source_run_state,
                blocking_reason=OperatorBlockViewV1(
                    code="official_schedule_missing",
                    message=message,
                    repair_owner="外部采集",
                    reevaluate_at=None,
                    recovery_link=recovery_link,
                ),
                next_action=WorkItemActionViewV1(
                    action_code="collect_official_schedule",
                    action_label="恢复官方赛程采集",
                    enabled=False,
                    recovery_link=recovery_link,
                ),
            )
        )
    return tuple(recoveries)


class OperatorWorkbenchAssembler:
    """Translate existing governed task facts into strict operator DTOs."""

    def __init__(
        self,
        *,
        slates: Sequence[SaleSlateSnapshot],
        built_tasks: Sequence[BuiltTaskViewSource],
        match_lookup: MatchLookup,
        evidence_count_lookup: EvidenceCountLookup | None = None,
        schedule_recoveries: Sequence[LaneScheduleRecoveryViewV1] = (),
    ) -> None:
        self._slates = tuple(slates)
        self._built = tuple(built_tasks)
        self._match_lookup = match_lookup
        self._evidence_counts = evidence_count_lookup or (lambda _match_id: (0, 0))
        self._schedule_recoveries = tuple(schedule_recoveries)

    def today(self, *, as_of: datetime) -> OperatorTodayResponseV1:
        cutoff = _aware(as_of, "as_of")
        task_views, priority_facts = self._views(cutoff)
        by_key = {
            (task.lane, task.business_key): task
            for task in task_views
        }
        entries_with_priority: list[tuple[TodayPriorityFacts, TodayWorkItemViewV1]] = []
        for facts in priority_facts:
            task = by_key[(facts.lane, str(facts.business_key))]
            work_item = next(
                (
                    item
                    for item in task.work_items
                    if item.work_item_key == facts.work_item_id
                ),
                None,
            )
            if work_item is None:
                raise ValueError("Today priority references an unknown work item")
            if work_item.next_action is None:
                continue
            entry = TodayWorkItemViewV1(
                lane=task.lane,
                business_key=task.business_key,
                task_label=task.task_label,
                scope_kind=work_item.scope_kind,
                scope_label=work_item.scope_label,
                phase=work_item.phase,
                deployment_outcome=work_item.deployment_outcome,
                next_deadline_at=work_item.next_deadline_at,
                progress=work_item.progress,
                blocking_reason=work_item.blocking_reason,
                next_action=work_item.next_action,
            )
            entries_with_priority.append((facts, entry))
        work_entries = [
            entry
            for _facts, entry in sorted(
                entries_with_priority,
                key=lambda item: today_priority_key(item[0], cutoff),
            )
        ]
        entries = [
            *work_entries,
            *sorted(
                self._schedule_recoveries,
                key=lambda item: (
                    item.lane.value,
                    item.shanghai_check_date,
                    item.recovery_key,
                ),
            ),
        ]
        return OperatorTodayResponseV1(
            as_of=cutoff,
            next_action=entries[0] if entries else None,
            entries=entries,
        )

    def lane(self, lane: OperatorLane, *, as_of: datetime) -> OperatorLaneResponseV1:
        cutoff = _aware(as_of, "as_of")
        task_views, priority_facts = self._views(cutoff)
        lane_tasks = [task for task in task_views if task.lane is lane]
        current = [task for task in lane_tasks if task.task_state == "current"]
        archive = [task for task in lane_tasks if task.task_state == "archive"]
        discovery = [
            DiscoveryTask(
                lane=task.lane,
                business_key=task.business_key,
                task_id=f"{task.lane.value}:{task.business_key}",
                state=(
                    SaleTaskState.CURRENT
                    if task.task_state == "current"
                    else SaleTaskState.ARCHIVE
                ),
                next_deadline_at=min(
                    (
                        item.next_deadline_at
                        for item in task.work_items
                        if item.next_deadline_at is not None
                    ),
                    default=None,
                ),
            )
            for task in lane_tasks
        ]
        focus = focus_business_key(
            lane,
            discovery,
            priority_facts,
            as_of=cutoff,
        )
        return OperatorLaneResponseV1(
            lane=lane,
            as_of=cutoff,
            focus_business_key=focus,
            current_tasks=sorted(current, key=self._task_sort_key),
            archive_tasks=sorted(archive, key=self._task_sort_key, reverse=True),
        )

    def task(
        self,
        lane: OperatorLane,
        business_key: str,
        *,
        as_of: datetime,
        work_item_key: str | None = None,
    ) -> OperatorTaskDetailV1:
        cutoff = _aware(as_of, "as_of")
        task_views, priorities = self._views(cutoff)
        summary = next(
            (
                item
                for item in task_views
                if item.lane is lane and item.business_key == business_key
            ),
            None,
        )
        if summary is None:
            raise ProductNotFoundError(
                f"operator task {lane.value}:{business_key} not found"
            )
        task_priorities = sorted(
            (
                item
                for item in priorities
                if item.lane is lane and item.business_key == business_key
            ),
            key=lambda item: today_priority_key(item, cutoff),
        )
        active_key = work_item_key or (
            task_priorities[0].work_item_id
            if task_priorities
            else summary.work_items[0].work_item_key
        )
        active_work_item = next(
            (
                item
                for item in summary.work_items
                if item.work_item_key == active_key
            ),
            None,
        )
        if active_work_item is None:
            raise ProductNotFoundError(
                f"operator work item {active_key} not found"
            )
        built = next(
            (
                item
                for item in self._built
                if item.facts.lane is lane
                and item.facts.business_key == business_key
                and _work_item_key(item, _scope_for_built(item, _state_for_built(item)))
                == active_key
            ),
            None,
        )
        if built is None:
            raise ProductNotFoundError(
                f"operator task {lane.value}:{business_key} has no phase detail"
            )
        return OperatorTaskDetailV1(
            as_of=cutoff,
            task_id=f"{lane.value}:{business_key}",
            lane=summary.lane,
            business_key=summary.business_key,
            task_label=summary.task_label,
            task_state=summary.task_state,
            current_slate=summary.current_slate,
            work_items=summary.work_items,
            active_work_item=active_work_item,
            step=built.step,
        )

    def _views(
        self,
        cutoff: datetime,
    ) -> tuple[list[OperatorTaskSummaryV1], list[TodayPriorityFacts]]:
        slates = {
            (slate.lane, slate.business_key): slate
            for slate in self._slates
        }
        grouped_items: dict[
            tuple[OperatorLane, str],
            tuple[SaleSlateSnapshot, list[OperatorWorkItemViewV1]],
        ] = {}
        priorities: list[TodayPriorityFacts] = []
        for built in self._built:
            facts = built.facts
            slate = slates.get((facts.lane, facts.business_key))
            if slate is None:
                continue
            state = _state_for_built(built)
            phase = _PHASE_BY_STATE[state]
            scope = _scope_for_built(built, state)
            work_item_key = _work_item_key(built, scope)
            recovery_link = (
                f"/operator-next/{facts.lane.value}/{facts.business_key}/"
                f"{work_item_key}"
            )
            block = _block_for_state(
                state,
                facts,
                built.step,
                recovery_link=recovery_link,
            )
            settlement_token = (
                built.step.settlement_command_token
                if isinstance(built.step, AwaitResultStep)
                else None
            )
            settlement_actionable = settlement_token is not None
            actionable = not (
                scope is ScopeKind.SALE_WAVE
                and is_passive_expired_deployment(facts, cutoff)
            ) and (
                settlement_actionable
                or block is not None
                or state
                not in {
                    OperatorTaskState.AWAIT_RESULT,
                    OperatorTaskState.COMPLETE,
                }
            )
            action = (
                WorkItemActionViewV1(
                    action_code=(
                        "request_settlement" if settlement_actionable else phase
                    ),
                    action_label=(
                        "确认并开始结算"
                        if settlement_actionable
                        else (
                            OPERATOR_RECOVERY_CATALOG[block.code].action_label
                            if block is not None
                            else _ACTION_LABELS[phase]
                        )
                    ),
                    enabled=block is None,
                    recovery_link=recovery_link,
                )
                if actionable
                else None
            )
            progress = WorkItemProgressViewV1(
                completed_count=built.progress.completed,
                required_count=built.progress.total,
                progress_label=built.progress.label,
            )
            expired_deployment = bool(
                scope is ScopeKind.SALE_WAVE
                and is_passive_expired_deployment(facts, cutoff)
            )
            work_item = OperatorWorkItemViewV1(
                work_item_key=work_item_key,
                scope_kind=scope.value,
                scope_label=(
                    getattr(built, "scope_label", None)
                    or _scope_label(scope, facts.lane)
                ),
                phase=phase,
                deployment_outcome=(
                    "expired"
                    if expired_deployment
                    else _deployment_outcome_for_built(built, scope)
                ),
                next_deadline_at=facts.deadline_at,
                is_current=actionable,
                snapshot_token=settlement_token or built.mutation_token,
                progress=progress,
                blocking_reason=block,
                next_action=action,
            )
            key = (facts.lane, facts.business_key)
            grouped = grouped_items.setdefault(key, (slate, []))[1]
            if any(item.work_item_key == work_item_key for item in grouped):
                raise ValueError("operator task contains a duplicate work-item key")
            grouped.append(work_item)
            if action is not None:
                priorities.append(
                    TodayPriorityFacts(
                        lane=facts.lane,
                        business_key=facts.business_key,
                        scope_kind=scope,
                        work_item_id=work_item_key,
                        phase=phase,
                        next_deadline_at=facts.deadline_at,
                        has_human_action=block is None,
                        evidence_complete=state
                        not in {
                            OperatorTaskState.WAITING_DATA,
                            OperatorTaskState.PREPARE,
                        },
                        externally_blocked=block is not None,
                        integrity_incident=state is OperatorTaskState.AWAIT_LEDGER,
                    )
                )
        views: list[OperatorTaskSummaryV1] = []
        for (lane, business_key), (slate, items) in grouped_items.items():
            task_priorities = sorted(
                (
                    item
                    for item in priorities
                    if item.lane is lane and item.business_key == business_key
                ),
                key=lambda item: today_priority_key(item, cutoff),
            )
            priority_keys = [item.work_item_id for item in task_priorities]
            by_work_item_key = {item.work_item_key: item for item in items}
            ordered_items = [by_work_item_key[key] for key in priority_keys]
            ordered_items.extend(
                sorted(
                    (
                        item
                        for item in items
                        if item.work_item_key not in set(priority_keys)
                    ),
                    key=lambda item: item.work_item_key,
                )
            )
            views.append(
                OperatorTaskSummaryV1(
                    lane=lane,
                    business_key=business_key,
                    task_label=_task_label(lane, business_key),
                    task_state=task_state(slate, cutoff).value,
                    current_slate=self._slate_view(slate, cutoff),
                    work_items=ordered_items,
                )
            )
        return views, priorities

    def _slate_view(
        self,
        slate: SaleSlateSnapshot,
        cutoff: datetime,
    ) -> OfficialSaleSlateViewV1:
        if slate.published_at is None or slate.retrieved_at is None:
            raise ValueError("official sale slate is missing display timestamps")
        offers = []
        for offer in slate.offers:
            match = self._match_lookup(offer.match_id, cutoff.isoformat())
            match_label = "身份待修复"
            competition_label = "赛事待修复"
            kickoff_at = offer.sale_deadline_at
            if match is not None:
                home = str(match.home_team or "主队待修复")
                away = str(match.away_team or "客队待修复")
                match_label = f"{home} vs {away}"
                competition_label = str(match.competition or "赛事待修复")
                kickoff_at = _datetime(match.scheduled_at, "match kickoff")
            complete, required = self._evidence_counts(offer.match_id)
            state = offer_state(offer, cutoff)
            markets = [
                self._market_view(market_definition_id, slate.lane)
                for market_definition_id in offer.market_definition_ids
            ]
            offers.append(
                OfficialOfferViewV1(
                    official_match_no=offer.official_match_no,
                    match_label=match_label,
                    competition_label=competition_label,
                    kickoff_at=kickoff_at,
                    sale_opens_at=offer.sale_opens_at,
                    sale_deadline_at=offer.sale_deadline_at,
                    offer_state=state.value,
                    markets=markets,
                    evidence_complete_count=complete,
                    evidence_required_count=required,
                    next_action=(
                        "查看工作项"
                        if state.value in {"upcoming", "open"}
                        else "查看历史"
                    ),
                )
            )
        open_offers = [
            item for item in offers if item.offer_state in {"upcoming", "open"}
        ]
        return OfficialSaleSlateViewV1(
            lane=slate.lane,
            business_key=slate.business_key,
            revision_no=slate.revision_no,
            state="current",
            published_at=slate.published_at,
            retrieved_at=slate.retrieved_at,
            next_deadline_at=(
                min(item.sale_deadline_at for item in open_offers)
                if open_offers
                else None
            ),
            total_offer_count=len(offers),
            open_offer_count=len(open_offers),
            offers=offers,
        )

    @staticmethod
    def _market_view(
        market_definition_id: str,
        lane: OperatorLane,
    ) -> OfferMarketViewV1:
        market_code = market_definition_id.removeprefix("md-")
        return OfferMarketViewV1(
            market_code=market_code,
            market_label=_MARKET_LABELS.get(market_code, market_code.upper()),
            settlement_policy_label=(
                "按官方奖级结算"
                if lane is OperatorLane.ZUCAI
                else "按票面赔率与官方赛果结算"
            ),
        )

    @staticmethod
    def _task_sort_key(task: OperatorTaskSummaryV1) -> tuple[datetime, str]:
        deadline = task.current_slate.next_deadline_at or datetime.max.replace(
            tzinfo=task.current_slate.published_at.tzinfo
        )
        return deadline, task.business_key


__all__ = ["OperatorWorkbenchAssembler", "schedule_recovery_views"]
