from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from nutmeg.product.operator_contracts import (
    LaneScheduleRecoveryViewV1,
    OfficialOfferViewV1,
    OfficialSaleSlateViewV1,
    OperatorBlockViewV1,
    OperatorLane,
    OperatorLaneResponseV1,
    OperatorRecoveryCode,
    OperatorTaskSummaryV1,
    OperatorTodayResponseV1,
    OperatorWorkItemViewV1,
    TodayQueueEntryV1,
    TodayWorkItemViewV1,
    WorkItemActionViewV1,
    WorkItemProgressViewV1,
)

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)


def _progress() -> WorkItemProgressViewV1:
    return WorkItemProgressViewV1(
        completed_count=2,
        required_count=14,
        progress_label="已完成 2 / 14 场",
    )


def _action() -> WorkItemActionViewV1:
    return WorkItemActionViewV1(
        action_code="continue_judgment",
        action_label="继续逐场裁决",
        enabled=True,
        recovery_link="/operator-next/zucai/26116",
    )


def _block() -> OperatorBlockViewV1:
    return OperatorBlockViewV1(
        code="evidence_missing",
        message="仍缺少两场赛前证据。",
        repair_owner="外部采集",
        reevaluate_at=NOW,
        recovery_link="/operator-next/zucai/26116",
    )


def _today_work_item(**changes: object) -> TodayWorkItemViewV1:
    payload: dict[str, object] = {
        "lane": OperatorLane.ZUCAI,
        "business_key": "26116",
        "task_label": "胜负彩 26116 期",
        "scope_kind": "sale_wave",
        "scope_label": "本期 14 场",
        "phase": "judge_matches",
        "deployment_outcome": "pending",
        "next_deadline_at": NOW,
        "progress": _progress(),
        "blocking_reason": None,
        "next_action": _action(),
    }
    payload.update(changes)
    return TodayWorkItemViewV1(**payload)


def _offer(**changes: object) -> OfficialOfferViewV1:
    payload: dict[str, object] = {
        "official_match_no": "001",
        "match_label": "主队 vs 客队",
        "competition_label": "测试联赛",
        "kickoff_at": NOW,
        "sale_opens_at": NOW,
        "sale_deadline_at": datetime(2026, 9, 5, 10, tzinfo=UTC),
        "offer_state": "open",
        "markets": [],
        "evidence_complete_count": 0,
        "evidence_required_count": 6,
        "next_action": "补齐证据",
    }
    payload.update(changes)
    return OfficialOfferViewV1(**payload)


def _slate() -> OfficialSaleSlateViewV1:
    return OfficialSaleSlateViewV1(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        revision_no=1,
        state="current",
        published_at=NOW,
        retrieved_at=NOW,
        next_deadline_at=datetime(2026, 9, 5, 10, tzinfo=UTC),
        total_offer_count=1,
        open_offer_count=1,
        offers=[_offer()],
    )


def test_today_contract_is_discriminated_and_has_one_explicit_next_action() -> None:
    work = _today_work_item()
    recovery = LaneScheduleRecoveryViewV1(
        lane=OperatorLane.JCZQ,
        shanghai_check_date="2026-09-05",
        recovery_key="jczq:2026-09-05:schedule",
        last_check_state="missing",
        last_checked_at=NOW,
        last_source_run_state="failed",
        blocking_reason=_block(),
        next_action=WorkItemActionViewV1(
            action_code="collect_official_schedule",
            action_label="恢复官方赛程采集",
            enabled=False,
            recovery_link="/operator-next/maintenance",
        ),
    )

    parsed = TypeAdapter(list[TodayQueueEntryV1]).validate_python(
        [work.model_dump(mode="python"), recovery.model_dump(mode="python")]
    )
    response = OperatorTodayResponseV1(
        as_of=NOW,
        next_action=work,
        entries=parsed,
    )

    assert response.next_action == response.entries[0]
    assert [entry.kind for entry in response.entries] == [
        "today_work_item_v1",
        "lane_schedule_recovery_v1",
    ]


def test_today_work_item_cannot_omit_its_operator_or_recovery_action() -> None:
    payload = _today_work_item().model_dump(mode="python")
    payload["next_action"] = None

    with pytest.raises(ValidationError):
        TodayWorkItemViewV1.model_validate(payload)


@pytest.mark.parametrize(
    ("scope_kind", "phase", "deployment_outcome"),
    [
        ("sale_wave", "waiting_schedule", "pending"),
        ("artifact", "judge_matches", "pending"),
        ("ticket", "await_confirmation", None),
        ("ticket", "await_result", "placed"),
        ("review", "await_result", None),
        ("review", "review", "expired"),
    ],
)
def test_work_item_contract_rejects_illegal_scope_phase_outcome_combinations(
    scope_kind: str,
    phase: str,
    deployment_outcome: str | None,
) -> None:
    payload = {
        "scope_kind": scope_kind,
        "scope_label": "测试工作项",
        "phase": phase,
        "deployment_outcome": deployment_outcome,
        "next_deadline_at": NOW,
        "is_current": True,
        "snapshot_token": "opaque-snapshot-token",
        "progress": _progress(),
        "blocking_reason": None,
        "next_action": None,
    }

    with pytest.raises(ValidationError):
        OperatorWorkItemViewV1.model_validate(payload)


def test_passive_and_archive_work_items_may_have_no_action() -> None:
    item = OperatorWorkItemViewV1(
        work_item_key="ticket-opaque0001",
        scope_kind="ticket",
        scope_label="已出票票据",
        phase="await_result",
        deployment_outcome=None,
        next_deadline_at=None,
        is_current=False,
        snapshot_token="opaque-snapshot-token",
        progress=_progress(),
        blocking_reason=None,
        next_action=None,
    )
    task = OperatorTaskSummaryV1(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        task_label="胜负彩 26116 期",
        task_state="archive",
        current_slate=_slate(),
        work_items=[item],
    )
    response = OperatorLaneResponseV1(
        lane=OperatorLane.ZUCAI,
        as_of=NOW,
        focus_business_key=None,
        current_tasks=[],
        archive_tasks=[task],
    )

    assert response.archive_tasks[0].work_items[0].next_action is None


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            OperatorTodayResponseV1,
            {
                "as_of": NOW,
                "next_action": None,
                "entries": [],
                "action_id": "internal-action",
            },
        ),
        (
            WorkItemProgressViewV1,
            {
                "completed_count": 0,
                "required_count": 1,
                "progress_label": "0 / 1",
                "raw_json": {},
            },
        ),
        (
            OfficialOfferViewV1,
            {
                **_offer().model_dump(mode="python"),
                "official_offer_revision_id": "internal-revision",
            },
        ),
    ],
)
def test_normal_contracts_reject_internal_or_arbitrary_extra_fields(
    model: type,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_operator_recovery_codes_are_closed_and_cover_the_public_matrix() -> None:
    codes = (
        "official_schedule_missing",
        "identity_unresolved",
        "evidence_missing",
        "evidence_stale",
        "evidence_conflict",
        "source_contract_invalid",
        "task_snapshot_changed",
        "audit_error",
        "confirmation_expired",
        "telegram_update_owner_conflict",
        "telegram_owner_missing",
        "telegram_owner_heartbeat_expired",
        "telegram_owner_clock_skew",
        "placement_ledger_integrity",
        "result_source_missing",
        "result_pending",
        "result_source_conflict",
        "projection_stale",
        "projection_unavailable",
        "app_instance_conflict",
    )

    for code in codes:
        block = _block().model_copy(update={"code": OperatorRecoveryCode(code)})
        assert OperatorBlockViewV1.model_validate(block.model_dump()).code == code

    with pytest.raises(ValidationError):
        OperatorBlockViewV1(
            code="totally_unstable",
            message="unknown",
            repair_owner="nobody",
            reevaluate_at=None,
            recovery_link="/operator-next",
        )


def test_contracts_reject_naive_times_and_integral_float_counts() -> None:
    with pytest.raises(ValidationError):
        OperatorTodayResponseV1(
            as_of=datetime(2026, 9, 5, 8),
            next_action=None,
            entries=[],
        )
    with pytest.raises(ValidationError):
        WorkItemProgressViewV1(
            completed_count=1.0,
            required_count=14,
            progress_label="1 / 14",
        )


def test_lane_focus_must_name_a_task_in_the_returned_lane() -> None:
    task = OperatorTaskSummaryV1(
        lane=OperatorLane.ZUCAI,
        business_key="26116",
        task_label="胜负彩 26116 期",
        task_state="current",
        current_slate=_slate(),
        work_items=[],
    )

    with pytest.raises(ValidationError):
        OperatorLaneResponseV1(
            lane=OperatorLane.ZUCAI,
            as_of=NOW,
            focus_business_key="26117",
            current_tasks=[task],
            archive_tasks=[],
        )
