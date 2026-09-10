from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, is_dataclass
from datetime import UTC, datetime, timedelta

import pytest

from nutmeg.product.operator_contracts import (
    CompleteStep,
    JudgeMatchesStep,
    LaneScheduleRecoveryViewV1,
    OperatorBlockViewV1,
    OperatorLane,
    OperatorTaskState,
    OperatorTaskSummary,
    ReviewItemSummary,
    ReviewStep,
    TaskProgressSummary,
    WorkItemActionViewV1,
)
from nutmeg.product.operator_lanes import (
    SaleOfferSnapshot,
    SaleSlateSnapshot,
    ScheduleRecoverySnapshot,
)
from nutmeg.product.operator_queries import OperatorQueryService, _BuiltTask
from nutmeg.product.operator_state import OperatorTaskFacts, resolve_state
from nutmeg.product.operator_workbench import OperatorWorkbenchAssembler
from nutmeg.product.repository import MatchReadRow, ProductReadRepository

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _TypedMatchLookupView:
    home_team: str | None
    away_team: str | None
    competition: str | None
    scheduled_at: datetime


class _Repository:
    def __init__(
        self,
        slates: tuple[SaleSlateSnapshot, ...],
        recoveries: tuple[ScheduleRecoverySnapshot, ...] = (),
    ) -> None:
        self.slates = slates
        self.recoveries = recoveries

    def operator_sale_slates(self, *, as_of: str) -> tuple[SaleSlateSnapshot, ...]:
        del as_of
        return self.slates

    def match(self, match_id: str, as_of: str) -> MatchReadRow:
        del as_of
        suffix = match_id.rsplit("-", 1)[-1]
        return MatchReadRow(
            match_id=match_id,
            match_revision_id=f"revision-{suffix}",
            scheduled_at=NOW + timedelta(hours=1),
            status="scheduled",
            schedule_status="confirmed",
            home_team=f"主队 {suffix}",
            away_team=f"客队 {suffix}",
            home_team_id=f"home-{suffix}",
            away_team_id=f"away-{suffix}",
            home_resolution_status="resolved",
            away_resolution_status="resolved",
            competition_id="competition-test",
            competition_edition_id="edition-test",
            competition="测试联赛",
            round_label=None,
            venue_id=None,
        )

    def operator_schedule_checks(
        self,
        *,
        as_of: str,
    ) -> tuple[ScheduleRecoverySnapshot, ...]:
        del as_of
        return self.recoveries


def _offer(suffix: str, *, deadline: datetime) -> SaleOfferSnapshot:
    return SaleOfferSnapshot(
        official_offer_family_id=f"family-{suffix}",
        official_offer_revision_id=f"offer-{suffix}",
        match_id=f"match-{suffix}",
        official_match_no=suffix,
        market_definition_ids=("md-had",),
        sale_opens_at=NOW - timedelta(hours=1),
        sale_deadline_at=deadline,
        source_status="on_sale" if deadline > NOW else "sale_closed",
    )


def _slate(
    lane: OperatorLane,
    business_key: str,
    suffix: str,
    *,
    deadline: datetime,
) -> SaleSlateSnapshot:
    return SaleSlateSnapshot(
        lane=lane,
        business_key=business_key,
        slate_revision_id=f"slate-{suffix}",
        content_hash=f"content-{suffix}",
        offers=(_offer(suffix, deadline=deadline),),
        source_official=True,
        revision_no=2,
        published_at=NOW - timedelta(hours=3),
        retrieved_at=NOW - timedelta(minutes=10),
    )


def _built(
    facts: OperatorTaskFacts,
    *,
    completed: int = 0,
    total: int = 1,
    token_character: str = "a",
    step_title: str = "测试",
) -> _BuiltTask:
    state = resolve_state(facts)
    task_id = f"{facts.lane.value}:{facts.business_key}"
    if state is OperatorTaskState.JUDGE_MATCHES:
        step = JudgeMatchesStep(
            task_id=task_id,
            item_key="fixture-judgment",
            title=step_title,
            prompt="测试",
            options=[],
        )
    elif state is OperatorTaskState.REVIEW:
        step = ReviewStep(
            task_id=task_id,
            title=step_title,
            current_item=ReviewItemSummary(
                item_type="prediction",
                item_id="fixture-review",
                title=step_title,
                allowed_outcomes=["hit", "miss", "na"],
            ),
        )
    else:
        step = CompleteStep(task_id=task_id, title=step_title, summary="测试")
    return _BuiltTask(
        facts=facts,
        summary=OperatorTaskSummary(
            task_id=task_id,
            lane=facts.lane,
            business_key=facts.business_key,
            title=task_id,
            state=state,
            deadline_at=facts.deadline_at,
            waiting_until=facts.waiting_until,
            is_actionable=state
            not in {
                OperatorTaskState.AWAIT_RESULT,
                OperatorTaskState.COMPLETE,
            },
            next_action_label="继续处理",
            priority_rank=0,
        ),
        progress=TaskProgressSummary(completed=completed, total=total, label="处理进度"),
        step=step,
        mutation_token=token_character * 64,
    )


def _facts(
    lane: OperatorLane,
    business_key: str,
    *,
    deadline: datetime | None,
    placement_state: str | None = None,
    result_available: bool = False,
    pending_review_items: int = 0,
    unresolved_adjudications: int = 0,
) -> OperatorTaskFacts:
    return OperatorTaskFacts(
        lane=lane,
        business_key=business_key,
        deadline_at=deadline,
        waiting_until=None,
        source_error_code=None,
        has_issue=True,
        has_prep=True,
        unresolved_adjudications=unresolved_adjudications,
        candidate_count=1,
        selected_candidate_id="selected",
        audit_recorded=True,
        deployment_decision="keep",
        ticket_artifact_id="artifact",
        confirmation_state="consumed",
        placement_state=placement_state,
        result_available=result_available,
        pending_review_items=pending_review_items,
    )


def test_sale_snapshot_retains_business_display_metadata() -> None:
    slate = SaleSlateSnapshot(
        lane=OperatorLane.JCZQ,
        business_key="2026-09-05",
        slate_revision_id="internal-slate-revision",
        content_hash="internal-content-hash",
        offers=(
            SaleOfferSnapshot(
                official_offer_family_id="family-1",
                official_offer_revision_id="offer-1",
                match_id="match-1",
                official_match_no="周六001",
                market_definition_ids=("md-had",),
                sale_opens_at=NOW - timedelta(hours=1),
                sale_deadline_at=NOW + timedelta(hours=2),
                source_status="on_sale",
            ),
        ),
        source_official=True,
        revision_no=3,
        published_at=NOW - timedelta(hours=2),
        retrieved_at=NOW - timedelta(minutes=5),
    )

    assert slate.revision_no == 3
    assert slate.published_at == NOW - timedelta(hours=2)
    assert slate.retrieved_at == NOW - timedelta(minutes=5)


def test_workbench_match_lookup_consumes_a_frozen_typed_view() -> None:
    slate = _slate(
        OperatorLane.ZUCAI,
        "26116",
        "1",
        deadline=NOW + timedelta(hours=2),
    )
    assembler = OperatorWorkbenchAssembler(
        slates=(slate,),
        built_tasks=(
            _built(
                _facts(
                    OperatorLane.ZUCAI,
                    "26116",
                    deadline=NOW + timedelta(hours=2),
                    unresolved_adjudications=1,
                )
            ),
        ),
        match_lookup=lambda _match_id, _as_of: _TypedMatchLookupView(
            home_team="阿尔法",
            away_team="贝塔",
            competition="测试联赛",
            scheduled_at=NOW + timedelta(hours=1),
        ),
    )

    task = assembler.lane(OperatorLane.ZUCAI, as_of=NOW).current_tasks[0]

    assert task.current_slate.offers[0].match_label == "阿尔法 vs 贝塔"
    assert task.current_slate.offers[0].competition_label == "测试联赛"


def test_product_repository_match_returns_a_frozen_typed_row(
    m3_seeded_product,
) -> None:
    repository = ProductReadRepository(m3_seeded_product.kernel.engine)

    row = repository.match("match-1", "2026-08-24T10:00:00+00:00")

    assert row is not None
    assert is_dataclass(row)
    assert row.home_team
    assert row["home_team"] == row.home_team
    assert row == dict(row)
    with pytest.raises(FrozenInstanceError):
        row.home_team = "变更"  # type: ignore[misc]


def test_today_and_lane_views_separate_actionable_review_and_passive_work() -> None:
    live_zucai = _slate(
        OperatorLane.ZUCAI,
        "26116",
        "1",
        deadline=NOW + timedelta(hours=2),
    )
    old_review = _slate(
        OperatorLane.ZUCAI,
        "26115",
        "2",
        deadline=NOW,
    )
    passive_result = _slate(
        OperatorLane.JCZQ,
        "2026-09-04",
        "3",
        deadline=NOW,
    )
    built = [
        _built(
            _facts(
                OperatorLane.ZUCAI,
                "26116",
                deadline=NOW + timedelta(hours=2),
                unresolved_adjudications=1,
            )
        ),
        _built(
            _facts(
                OperatorLane.ZUCAI,
                "26115",
                deadline=None,
                placement_state="placed",
                result_available=True,
                pending_review_items=1,
            ),
            completed=1,
        ),
        _built(
            _facts(
                OperatorLane.JCZQ,
                "2026-09-04",
                deadline=None,
                placement_state="placed",
                result_available=False,
            ),
            completed=1,
        ),
    ]
    queries = OperatorQueryService(
        repository=_Repository((live_zucai, old_review, passive_result)),
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
    )
    queries._build_all = lambda _cutoff: built  # type: ignore[method-assign]

    today = queries.today(as_of=NOW)
    zucai = queries.lane(OperatorLane.ZUCAI, as_of=NOW)
    jczq = queries.lane(OperatorLane.JCZQ, as_of=NOW)

    assert [entry.business_key for entry in today.entries] == ["26116", "26115"]
    assert today.next_action == today.entries[0]
    assert [entry.phase for entry in today.entries] == ["judge_matches", "review"]
    assert zucai.focus_business_key == "26116"
    assert [task.business_key for task in zucai.current_tasks] == ["26116"]
    assert [task.business_key for task in zucai.archive_tasks] == ["26115"]
    assert jczq.focus_business_key is None
    assert jczq.current_tasks == []
    assert [task.business_key for task in jczq.archive_tasks] == ["2026-09-04"]
    assert all(entry.business_key != "2026-09-04" for entry in today.entries)


def test_task_v2_rejects_lane_business_key_mismatch() -> None:
    slate = _slate(
        OperatorLane.ZUCAI,
        "26116",
        "1",
        deadline=NOW + timedelta(hours=2),
    )
    queries = OperatorQueryService(
        repository=_Repository((slate,)),
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
    )
    queries._build_all = lambda _cutoff: [  # type: ignore[method-assign]
        _built(
            _facts(
                OperatorLane.ZUCAI,
                "26116",
                deadline=NOW + timedelta(hours=2),
                unresolved_adjudications=1,
            )
        )
    ]

    with pytest.raises(ValueError, match="business key"):
        queries.task_v2(OperatorLane.JCZQ, "26116", as_of=NOW)


def test_task_v2_includes_the_current_phase_detail_without_expanding_lane_rows() -> None:
    slate = _slate(
        OperatorLane.ZUCAI,
        "26116",
        "1",
        deadline=NOW + timedelta(hours=2),
    )
    built = _built(
        _facts(
            OperatorLane.ZUCAI,
            "26116",
            deadline=NOW + timedelta(hours=2),
            unresolved_adjudications=1,
        )
    )
    queries = OperatorQueryService(
        repository=_Repository((slate,)),
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
    )
    queries._build_all = lambda _cutoff: [built]  # type: ignore[method-assign]

    task = queries.task_v2(OperatorLane.ZUCAI, "26116", as_of=NOW)
    lane = queries.lane(OperatorLane.ZUCAI, as_of=NOW)

    assert task.business_key == "26116"
    assert task.step.kind == built.step.kind
    assert task.active_work_item.scope_kind == "sale_wave"
    assert not hasattr(lane.current_tasks[0], "step")


def test_same_task_aggregates_distinct_work_items_and_selects_the_priority_child() -> None:
    slate = _slate(
        OperatorLane.ZUCAI,
        "26116",
        "1",
        deadline=NOW + timedelta(hours=2),
    )
    review = _built(
        _facts(
            OperatorLane.ZUCAI,
            "26116",
            deadline=None,
            placement_state="placed",
            result_available=True,
            pending_review_items=1,
        ),
        token_character="b",
        step_title="复盘 child",
    )
    judgment = _built(
        _facts(
            OperatorLane.ZUCAI,
            "26116",
            deadline=NOW + timedelta(hours=2),
            unresolved_adjudications=1,
        ),
        token_character="a",
        step_title="裁决 child",
    )
    queries = OperatorQueryService(
        repository=_Repository((slate,)),
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
    )
    queries._build_all = lambda _cutoff: [review, judgment]  # type: ignore[method-assign]

    lane = queries.lane(OperatorLane.ZUCAI, as_of=NOW)
    task = queries.task_v2(OperatorLane.ZUCAI, "26116", as_of=NOW)

    assert len(lane.current_tasks) == 1
    assert len(lane.current_tasks[0].work_items) == 2
    keys = [item.work_item_key for item in lane.current_tasks[0].work_items]
    assert len(set(keys)) == 2
    assert task.active_work_item.phase == "judge_matches"
    assert task.step.title == "裁决 child"


def test_work_item_detail_selects_the_step_bound_to_the_requested_child() -> None:
    slate = _slate(
        OperatorLane.ZUCAI,
        "26116",
        "1",
        deadline=NOW + timedelta(hours=2),
    )
    review = _built(
        _facts(
            OperatorLane.ZUCAI,
            "26116",
            deadline=None,
            placement_state="placed",
            result_available=True,
            pending_review_items=1,
        ),
        token_character="b",
        step_title="复盘 child",
    )
    judgment = _built(
        _facts(
            OperatorLane.ZUCAI,
            "26116",
            deadline=NOW + timedelta(hours=2),
            unresolved_adjudications=1,
        ),
        token_character="a",
        step_title="裁决 child",
    )
    queries = OperatorQueryService(
        repository=_Repository((slate,)),
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
    )
    queries._build_all = lambda _cutoff: [review, judgment]  # type: ignore[method-assign]
    lane = queries.lane(OperatorLane.ZUCAI, as_of=NOW)
    review_key = next(
        item.work_item_key
        for item in lane.current_tasks[0].work_items
        if item.phase == "review"
    )

    detail = queries.work_item_v2(
        OperatorLane.ZUCAI,
        "26116",
        review_key,
        as_of=NOW,
    )

    assert detail.active_work_item.work_item_key == review_key
    assert detail.active_work_item.phase == "review"
    assert detail.step.title == "复盘 child"


def test_lane_schedule_recovery_is_last_and_does_not_create_focus() -> None:
    recovery = LaneScheduleRecoveryViewV1(
        lane=OperatorLane.JCZQ,
        shanghai_check_date="2026-09-05",
        recovery_key="jczq:2026-09-05:schedule",
        last_check_state="failed",
        last_checked_at=NOW - timedelta(minutes=10),
        last_source_run_state="failed",
        blocking_reason=OperatorBlockViewV1(
            code="official_schedule_missing",
            message="今日官方竞彩赛程检查失败。",
            repair_owner="外部采集",
            reevaluate_at=None,
            recovery_link="/operator-next/maintenance",
        ),
        next_action=WorkItemActionViewV1(
            action_code="collect_official_schedule",
            action_label="恢复官方赛程采集",
            enabled=False,
            recovery_link="/operator-next/maintenance",
        ),
    )
    assembler = OperatorWorkbenchAssembler(
        slates=(),
        built_tasks=(),
        match_lookup=lambda _match_id, _as_of: None,
        schedule_recoveries=(recovery,),
    )

    today = assembler.today(as_of=NOW)
    lane = assembler.lane(OperatorLane.JCZQ, as_of=NOW)

    assert [entry.kind for entry in today.entries] == ["lane_schedule_recovery_v1"]
    assert today.next_action == recovery
    assert lane.focus_business_key is None
    assert lane.current_tasks == []


def test_query_service_exposes_only_missing_or_failed_schedule_checks() -> None:
    checks = (
        ScheduleRecoverySnapshot(
            lane=OperatorLane.JCZQ,
            shanghai_check_date="2026-09-05",
            last_check_state=None,
            last_checked_at=None,
            last_source_run_state=None,
            error_code=None,
        ),
        ScheduleRecoverySnapshot(
            lane=OperatorLane.ZUCAI,
            shanghai_check_date="2026-09-05",
            last_check_state="confirmed_no_sale",
            last_checked_at=NOW - timedelta(minutes=5),
            last_source_run_state="succeeded",
            error_code=None,
        ),
    )
    queries = OperatorQueryService(
        repository=_Repository((), checks),
        product_queries=object(),
        official_history_provider=lambda: [],
        clock=lambda: NOW,
    )
    queries._build_all = lambda _cutoff: []  # type: ignore[method-assign]

    today = queries.today(as_of=NOW)

    assert len(today.entries) == 1
    recovery = today.entries[0]
    assert recovery.kind == "lane_schedule_recovery_v1"
    assert recovery.lane is OperatorLane.JCZQ
    assert recovery.blocking_reason.code == "official_schedule_missing"
