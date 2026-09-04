from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from nutmeg.product.operator_contracts import OperatorLane
from nutmeg.product.operator_lanes import (
    CandidateLaneInputs,
    DiscoveryTask,
    JczqLaneAdapter,
    NoTicketClosure,
    OfferState,
    SaleOfferSnapshot,
    SaleSlateAdapter,
    SaleSlateSnapshot,
    SaleTaskState,
    ScopeKind,
    TodayPriorityFacts,
    ZucaiLaneAdapter,
    derive_sale_wave,
    focus_business_key,
    offer_state,
    task_snapshot_hash,
    task_state,
    today_priority_key,
)

NOW = datetime(2026, 9, 4, 10, tzinfo=UTC)


def _offer(
    suffix: str,
    *,
    opens_at: datetime | None = None,
    deadline_at: datetime | None = None,
    status: str = "on_sale",
    official_match_no: str | None = None,
    removed: bool = False,
    revision_no: int = 1,
) -> SaleOfferSnapshot:
    return SaleOfferSnapshot(
        official_offer_family_id=f"family-{suffix}",
        official_offer_revision_id=f"offer-{suffix}-r{revision_no}",
        match_id=f"match-{suffix}",
        official_match_no=official_match_no or f"周五{int(suffix):03d}",
        market_definition_ids=("md-had",),
        sale_opens_at=opens_at or NOW - timedelta(hours=1),
        sale_deadline_at=deadline_at or NOW + timedelta(hours=1),
        source_status=status,
        removed_from_current_revision=removed,
    )


def _slate(
    *offers: SaleOfferSnapshot,
    lane: OperatorLane = OperatorLane.JCZQ,
    business_key: str = "2026-09-04",
    revision_no: int = 1,
) -> SaleSlateSnapshot:
    return SaleSlateSnapshot(
        lane=lane,
        business_key=business_key,
        slate_revision_id=f"slate-{business_key}-r{revision_no}",
        content_hash=f"content-{revision_no}",
        offers=tuple(offers),
    )


def _task(
    slate: SaleSlateSnapshot,
    *,
    as_of: datetime = NOW,
    next_deadline_at: datetime | None = None,
) -> DiscoveryTask:
    return DiscoveryTask(
        lane=slate.lane,
        business_key=slate.business_key,
        task_id=f"{slate.lane.value}:{slate.business_key}",
        state=task_state(slate, as_of),
        next_deadline_at=next_deadline_at,
    )


def test_offer_state_uses_exact_boundaries_and_terminal_precedence() -> None:
    offer = _offer(
        "1",
        opens_at=NOW,
        deadline_at=NOW + timedelta(hours=2),
        status="scheduled",
    )

    assert offer_state(offer, NOW - timedelta(microseconds=1)) is OfferState.UPCOMING
    assert offer_state(offer, NOW) is OfferState.OPEN
    assert offer_state(offer, NOW + timedelta(hours=2)) is OfferState.CLOSED
    assert (
        offer_state(replace(offer, source_status="sale_closed"), NOW)
        is OfferState.CLOSED
    )
    assert (
        offer_state(replace(offer, source_status="cancelled"), NOW)
        is OfferState.CANCELLED
    )
    assert (
        offer_state(replace(offer, removed_from_current_revision=True), NOW)
        is OfferState.CANCELLED
    )


def test_task_hash_ignores_raw_as_of_but_changes_at_offer_state_transition() -> None:
    slate = _slate(
        _offer(
            "1",
            opens_at=NOW,
            deadline_at=NOW + timedelta(hours=2),
            status="scheduled",
        )
    )

    during_open = task_snapshot_hash(slate, NOW)
    later_during_open = task_snapshot_hash(slate, NOW + timedelta(minutes=30))
    at_deadline = task_snapshot_hash(slate, NOW + timedelta(hours=2))

    assert during_open == later_during_open
    assert at_deadline != during_open
    assert len(during_open) == 64


def test_new_offer_creates_new_wave_without_reopening_no_ticket_families() -> None:
    first = _slate(_offer("1"), _offer("2"))
    closures = (
        NoTicketClosure("family-1", "offer-1-r1"),
        NoTicketClosure("family-2", "offer-2-r1"),
    )

    assert derive_sale_wave(first, NOW, no_ticket_closures=closures) is None

    corrected = _slate(
        _offer("1", revision_no=2),
        _offer("2", revision_no=2),
        _offer("3", revision_no=1),
        revision_no=2,
    )
    wave = derive_sale_wave(corrected, NOW, no_ticket_closures=closures)

    assert wave is not None
    assert wave.offer_family_ids == ("family-3",)
    assert wave.offer_revision_ids == ("offer-3-r1",)
    assert wave.work_item_id.startswith(
        f"jczq:2026-09-04:{wave.task_snapshot_hash}:sale_wave:"
    )


def test_jczq_wave_rolls_to_later_deadline_after_early_offer_closes() -> None:
    early_deadline = NOW + timedelta(hours=1)
    late_deadline = NOW + timedelta(hours=4)
    slate = _slate(
        _offer("1", deadline_at=early_deadline),
        _offer("2", deadline_at=late_deadline),
    )

    before = derive_sale_wave(slate, NOW)
    at_early_deadline = derive_sale_wave(slate, early_deadline)

    assert before is not None
    assert before.offer_family_ids == ("family-1", "family-2")
    assert before.next_deadline_at == early_deadline
    assert at_early_deadline is not None
    assert at_early_deadline.offer_family_ids == ("family-2",)
    assert at_early_deadline.next_deadline_at == late_deadline
    assert at_early_deadline.work_item_id != before.work_item_id


def test_lane_adapters_keep_offer_count_order_and_markets_out_of_shared_resolver() -> None:
    jczq = _slate(_offer("1"), _offer("2"))
    zucai = _slate(
        *(
            _offer(str(number), official_match_no=str(number))
            for number in range(1, 15)
        ),
        lane=OperatorLane.ZUCAI,
        business_key="26118",
    )
    jczq_adapter: SaleSlateAdapter = JczqLaneAdapter()
    zucai_adapter: SaleSlateAdapter = ZucaiLaneAdapter()

    jczq_adapter.validate_slate(jczq)
    zucai_adapter.validate_slate(zucai)
    inputs = zucai_adapter.candidate_inputs(zucai, NOW)

    assert isinstance(inputs, CandidateLaneInputs)
    assert inputs.offer_family_ids == tuple(f"family-{number}" for number in range(1, 15))
    with pytest.raises(ValueError, match="exactly 14"):
        zucai_adapter.validate_slate(replace(zucai, offers=zucai.offers[:-1]))


def test_task_state_supports_multiple_live_keys_and_tomorrow_presale() -> None:
    first = _slate(
        _offer("1", deadline_at=NOW + timedelta(hours=6)),
        lane=OperatorLane.ZUCAI,
        business_key="26118",
    )
    earlier_deadline = _slate(
        _offer("2", deadline_at=NOW + timedelta(hours=2)),
        lane=OperatorLane.ZUCAI,
        business_key="26119",
    )
    tomorrow = _slate(
        _offer(
            "3",
            opens_at=NOW + timedelta(hours=8),
            deadline_at=NOW + timedelta(days=1),
            status="scheduled",
        ),
        business_key="2026-09-05",
    )

    assert task_state(first, NOW) is SaleTaskState.CURRENT
    assert task_state(earlier_deadline, NOW) is SaleTaskState.CURRENT
    assert task_state(tomorrow, NOW) is SaleTaskState.CURRENT
    assert (
        focus_business_key(
            OperatorLane.ZUCAI,
            (
                _task(first, next_deadline_at=NOW + timedelta(hours=6)),
                _task(earlier_deadline, next_deadline_at=NOW + timedelta(hours=2)),
            ),
            (),
            as_of=NOW,
        )
        == "26119"
    )


def test_open_confirmation_keeps_task_current_until_exact_cutoff() -> None:
    closed = _slate(_offer("1", deadline_at=NOW))
    challenge_deadline = NOW + timedelta(minutes=5)

    assert (
        task_state(
            closed,
            NOW,
            open_confirmation_deadlines=(challenge_deadline,),
        )
        is SaleTaskState.CURRENT
    )
    assert (
        task_state(
            closed,
            challenge_deadline,
            open_confirmation_deadlines=(challenge_deadline,),
        )
        is SaleTaskState.ARCHIVE
    )


def test_recovery_only_lane_has_null_focus() -> None:
    recovery = TodayPriorityFacts(
        lane=OperatorLane.JCZQ,
        business_key=None,
        scope_kind=None,
        work_item_id="schedule:2026-09-04",
        phase="waiting_schedule",
        next_deadline_at=None,
        has_human_action=False,
        evidence_complete=False,
        externally_blocked=True,
    )

    assert (
        focus_business_key(
            OperatorLane.JCZQ,
            (),
            (recovery,),
            as_of=NOW,
        )
        is None
    )


def test_historical_review_can_supply_focus_without_making_task_current() -> None:
    closed_slate = _slate(
        _offer("1", deadline_at=NOW),
        lane=OperatorLane.ZUCAI,
        business_key="26113",
    )
    archived = _task(closed_slate, next_deadline_at=None)
    review = TodayPriorityFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26113",
        scope_kind=ScopeKind.REVIEW,
        work_item_id="review:26113:1",
        phase="review",
        next_deadline_at=None,
        has_human_action=True,
        evidence_complete=True,
        externally_blocked=False,
    )

    assert archived.state is SaleTaskState.ARCHIVE
    assert (
        focus_business_key(
            OperatorLane.ZUCAI,
            (archived,),
            (review,),
            as_of=NOW,
        )
        == "26113"
    )


def test_live_deadline_precedes_old_review_and_all_closed_lane_stays_archive() -> None:
    live_slate = _slate(
        _offer("1", deadline_at=NOW + timedelta(hours=1)),
        lane=OperatorLane.ZUCAI,
        business_key="26118",
    )
    closed_slate = _slate(
        _offer("2", deadline_at=NOW),
        lane=OperatorLane.ZUCAI,
        business_key="26113",
    )
    live_entry = TodayPriorityFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26118",
        scope_kind=ScopeKind.SALE_WAVE,
        work_item_id="wave:26118:1",
        phase="judge_matches",
        next_deadline_at=NOW + timedelta(hours=1),
        has_human_action=True,
        evidence_complete=True,
        externally_blocked=False,
    )
    review_entry = TodayPriorityFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26113",
        scope_kind=ScopeKind.REVIEW,
        work_item_id="review:26113:1",
        phase="review",
        next_deadline_at=None,
        has_human_action=True,
        evidence_complete=True,
        externally_blocked=False,
    )

    assert today_priority_key(live_entry, NOW) < today_priority_key(review_entry, NOW)
    assert (
        focus_business_key(
            OperatorLane.ZUCAI,
            (
                _task(live_slate, next_deadline_at=NOW + timedelta(hours=1)),
                _task(closed_slate),
            ),
            (review_entry, live_entry),
            as_of=NOW,
        )
        == "26118"
    )
    assert task_state(closed_slate, NOW) is SaleTaskState.ARCHIVE
    assert (
        focus_business_key(
            OperatorLane.ZUCAI,
            (_task(closed_slate),),
            (),
            as_of=NOW,
        )
        is None
    )


def test_review_and_integrity_incident_keep_their_declared_priority_classes() -> None:
    no_deadline_action = TodayPriorityFacts(
        lane=OperatorLane.ZUCAI,
        business_key="26118",
        scope_kind=ScopeKind.SALE_WAVE,
        work_item_id="wave:26118:1",
        phase="judge_matches",
        next_deadline_at=None,
        has_human_action=True,
        evidence_complete=True,
        externally_blocked=False,
    )
    review = replace(
        no_deadline_action,
        business_key="26113",
        scope_kind=ScopeKind.REVIEW,
        work_item_id="review:26113:1",
        phase="review",
    )
    integrity = replace(
        no_deadline_action,
        business_key="26117",
        scope_kind=ScopeKind.TICKET,
        work_item_id="ticket:26117:1",
        phase="blocked",
        has_human_action=False,
        evidence_complete=False,
        integrity_incident=True,
    )

    assert today_priority_key(integrity, NOW) < today_priority_key(no_deadline_action, NOW)
    assert today_priority_key(no_deadline_action, NOW) < today_priority_key(review, NOW)


def test_today_priority_rejects_naive_next_deadline() -> None:
    facts = TodayPriorityFacts(
        lane=OperatorLane.JCZQ,
        business_key="2026-09-04",
        scope_kind=ScopeKind.SALE_WAVE,
        work_item_id="work-naive",
        phase="judge_matches",
        next_deadline_at=datetime(2026, 9, 4, 19, 0),
        has_human_action=True,
        evidence_complete=True,
        externally_blocked=False,
    )

    with pytest.raises(ValueError, match="next_deadline_at must be timezone-aware"):
        today_priority_key(facts, NOW)


def test_lane_adapters_reject_market_definitions_owned_by_the_other_boundary() -> None:
    invalid_jczq = _slate(
        replace(_offer("1"), market_definition_ids=("md-unknown",))
    )
    invalid_zucai = _slate(
        *(
            replace(
                _offer(str(number), official_match_no=str(number)),
                market_definition_ids=("md-hhad",) if number == 14 else ("md-had",),
            )
            for number in range(1, 15)
        ),
        lane=OperatorLane.ZUCAI,
        business_key="26118",
    )

    with pytest.raises(ValueError, match="market definition"):
        JczqLaneAdapter().validate_slate(invalid_jczq)
    with pytest.raises(ValueError, match="market definition"):
        ZucaiLaneAdapter().validate_slate(invalid_zucai)


def test_jczq_adapter_rejects_duplicate_official_order() -> None:
    duplicate = _slate(
        _offer("1", official_match_no="周五001"),
        _offer("2", official_match_no="周五001"),
    )

    with pytest.raises(ValueError, match="official order"):
        JczqLaneAdapter().validate_slate(duplicate)


def test_lane_adapter_excludes_terminal_offers_from_readiness_and_candidates() -> None:
    active = _offer("1")
    closed = _offer("2", status="sale_closed")
    cancelled = _offer("3", status="cancelled")
    removed = _offer("4", removed=True)
    timed_out = _offer("5", deadline_at=NOW)
    slate = _slate(active, closed, cancelled, removed, timed_out)
    adapter = JczqLaneAdapter()

    assert adapter.evidence_offer_ids(slate, NOW) == (active.official_offer_revision_id,)
    inputs = adapter.candidate_inputs(slate, NOW)
    assert inputs.offer_family_ids == (active.official_offer_family_id,)
    assert inputs.offer_revision_ids == (active.official_offer_revision_id,)
    assert adapter.result_offer_ids(slate) == tuple(
        offer.official_offer_revision_id for offer in slate.offers
    )


def test_today_priority_api_cannot_accept_football_value_inputs() -> None:
    forbidden_names = {
        "odds",
        "forecast",
        "probability",
        "confidence",
        "ev",
        "expected_value",
    }
    input_names = {field.name for field in fields(TodayPriorityFacts)}
    candidate_names = {field.name for field in fields(CandidateLaneInputs)}

    assert forbidden_names.isdisjoint(input_names | candidate_names)
