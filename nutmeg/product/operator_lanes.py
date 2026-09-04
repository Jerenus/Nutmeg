"""Pure dual-lane sale discovery and work-item identity helpers."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, Sequence

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.product.operator_contracts import OperatorLane

_JCZQ_MARKET_DEFINITION_IDS = frozenset(
    {"md-had", "md-hhad", "md-ttg", "md-crs"}
)
_ZUCAI_MARKET_DEFINITION_IDS = frozenset({"md-had"})


class OfferState(StrEnum):
    UPCOMING = "upcoming"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class SaleTaskState(StrEnum):
    CURRENT = "current"
    ARCHIVE = "archive"


class ScopeKind(StrEnum):
    SALE_WAVE = "sale_wave"
    ARTIFACT = "artifact"
    TICKET = "ticket"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class SaleOfferSnapshot:
    official_offer_family_id: str
    official_offer_revision_id: str
    match_id: str
    official_match_no: str
    market_definition_ids: tuple[str, ...]
    sale_opens_at: datetime
    sale_deadline_at: datetime
    source_status: str
    removed_from_current_revision: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.sale_opens_at, "sale_opens_at")
        _require_aware(self.sale_deadline_at, "sale_deadline_at")
        if self.sale_opens_at >= self.sale_deadline_at:
            raise ValueError("sale opening must precede deadline")
        if self.source_status not in {
            "scheduled",
            "on_sale",
            "sale_closed",
            "cancelled",
        }:
            raise ValueError("unknown official offer status")


@dataclass(frozen=True, slots=True)
class SaleSlateSnapshot:
    lane: OperatorLane
    business_key: str
    slate_revision_id: str
    content_hash: str
    offers: tuple[SaleOfferSnapshot, ...]
    source_official: bool = False


@dataclass(frozen=True, slots=True)
class NoTicketClosure:
    official_offer_family_id: str
    official_offer_revision_id: str


@dataclass(frozen=True, slots=True)
class CandidateLaneInputs:
    lane: OperatorLane
    offer_family_ids: tuple[str, ...]
    offer_revision_ids: tuple[str, ...]
    market_definition_ids: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class SaleWave:
    task_id: str
    work_item_id: str
    task_snapshot_hash: str
    scope_kind: ScopeKind
    offer_family_ids: tuple[str, ...]
    offer_revision_ids: tuple[str, ...]
    next_deadline_at: datetime


@dataclass(frozen=True, slots=True)
class DiscoveryTask:
    lane: OperatorLane
    business_key: str
    task_id: str
    state: SaleTaskState
    next_deadline_at: datetime | None


@dataclass(frozen=True, slots=True)
class TodayPriorityFacts:
    lane: OperatorLane
    business_key: str | None
    scope_kind: ScopeKind | None
    work_item_id: str
    phase: str
    next_deadline_at: datetime | None
    has_human_action: bool
    evidence_complete: bool
    externally_blocked: bool
    integrity_incident: bool = False


class OperatorLaneAdapter(Protocol):
    """Shared lane contract for official sale discovery inputs."""

    lane: OperatorLane

    def validate_slate(self, slate: SaleSlateSnapshot) -> None: ...

    def evidence_offer_ids(
        self, slate: SaleSlateSnapshot, as_of: datetime
    ) -> Sequence[str]: ...

    def candidate_inputs(
        self, slate: SaleSlateSnapshot, as_of: datetime
    ) -> CandidateLaneInputs: ...

    def result_offer_ids(self, slate: SaleSlateSnapshot) -> Sequence[str]: ...


# Compatibility for callers written while Package 2 used its temporary protocol name.
SaleSlateAdapter = OperatorLaneAdapter


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def offer_state(offer: SaleOfferSnapshot, as_of: datetime) -> OfferState:
    _require_aware(as_of, "as_of")
    if offer.removed_from_current_revision or offer.source_status == "cancelled":
        return OfferState.CANCELLED
    if offer.source_status == "sale_closed" or offer.sale_deadline_at <= as_of:
        return OfferState.CLOSED
    if as_of < offer.sale_opens_at:
        return OfferState.UPCOMING
    return OfferState.OPEN


def _offer_sort_key(offer: SaleOfferSnapshot) -> tuple[str, int, str, str, str]:
    match = re.fullmatch(r"(?P<prefix>.*?)(?P<number>[0-9]+)", offer.official_match_no)
    prefix = match.group("prefix") if match else offer.official_match_no
    number = int(match.group("number")) if match else 0
    return (
        prefix,
        number,
        offer.official_match_no,
        offer.official_offer_family_id,
        offer.official_offer_revision_id,
    )


def task_snapshot_hash(
    slate: SaleSlateSnapshot,
    as_of: datetime,
    *,
    no_ticket_closures: Sequence[NoTicketClosure] = (),
) -> str:
    _require_aware(as_of, "as_of")
    document = {
        "lane": slate.lane.value,
        "business_key": slate.business_key,
        "slate_revision_id": slate.slate_revision_id,
        "slate_content_hash": slate.content_hash,
        "offers": [
            {
                "official_offer_family_id": offer.official_offer_family_id,
                "official_offer_revision_id": offer.official_offer_revision_id,
                "match_id": offer.match_id,
                "official_match_no": offer.official_match_no,
                "market_definition_ids": list(offer.market_definition_ids),
                "sale_opens_at": offer.sale_opens_at.astimezone(UTC).isoformat(),
                "sale_deadline_at": offer.sale_deadline_at.astimezone(UTC).isoformat(),
                "source_status": offer.source_status,
                "derived_state": offer_state(offer, as_of).value,
            }
            for offer in sorted(slate.offers, key=_offer_sort_key)
        ],
        "no_ticket_closures": [
            {
                "official_offer_family_id": family_id,
                "official_offer_revision_id": revision_id,
            }
            for family_id, revision_id in sorted(
                {
                    (
                        closure.official_offer_family_id,
                        closure.official_offer_revision_id,
                    )
                    for closure in no_ticket_closures
                }
            )
        ],
    }
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def derive_sale_wave(
    slate: SaleSlateSnapshot,
    as_of: datetime,
    *,
    no_ticket_closures: Sequence[NoTicketClosure] = (),
) -> SaleWave | None:
    closed_families = {
        closure.official_offer_family_id for closure in no_ticket_closures
    }
    actionable = tuple(sorted((
        offer
        for offer in slate.offers
        if offer.official_offer_family_id not in closed_families
        and offer_state(offer, as_of) in {OfferState.UPCOMING, OfferState.OPEN}
    ), key=_offer_sort_key))
    if not actionable:
        return None
    snapshot_hash = task_snapshot_hash(
        slate,
        as_of,
        no_ticket_closures=no_ticket_closures,
    )
    family_ids = tuple(offer.official_offer_family_id for offer in actionable)
    revision_ids = tuple(offer.official_offer_revision_id for offer in actionable)
    scope_key = hashlib.sha256(
        canonical_json(
            {"families": list(family_ids), "revisions": list(revision_ids)}
        ).encode("utf-8")
    ).hexdigest()[:16]
    task_id = f"{slate.lane.value}:{slate.business_key}"
    return SaleWave(
        task_id=task_id,
        work_item_id=(
            f"{task_id}:{snapshot_hash}:{ScopeKind.SALE_WAVE.value}:{scope_key}"
        ),
        task_snapshot_hash=snapshot_hash,
        scope_kind=ScopeKind.SALE_WAVE,
        offer_family_ids=family_ids,
        offer_revision_ids=revision_ids,
        next_deadline_at=min(offer.sale_deadline_at for offer in actionable),
    )


def task_state(
    slate: SaleSlateSnapshot,
    as_of: datetime,
    *,
    open_confirmation_deadlines: Sequence[datetime] = (),
) -> SaleTaskState:
    _require_aware(as_of, "as_of")
    if any(
        offer_state(offer, as_of) in {OfferState.UPCOMING, OfferState.OPEN}
        for offer in slate.offers
    ):
        return SaleTaskState.CURRENT
    for deadline in open_confirmation_deadlines:
        _require_aware(deadline, "confirmation deadline")
        if deadline > as_of:
            return SaleTaskState.CURRENT
    return SaleTaskState.ARCHIVE


_FAR_FUTURE = datetime.max.replace(tzinfo=UTC)


def today_priority_key(
    facts: TodayPriorityFacts,
    as_of: datetime,
) -> tuple[int, datetime, str, str, str, str]:
    _require_aware(as_of, "as_of")
    if facts.next_deadline_at is not None:
        _require_aware(facts.next_deadline_at, "next_deadline_at")
    deadline = facts.next_deadline_at or _FAR_FUTURE
    if facts.scope_kind is ScopeKind.REVIEW:
        category = 4
    elif facts.integrity_incident:
        category = 1
    elif facts.has_human_action and facts.next_deadline_at is not None and deadline > as_of:
        category = 0
    elif facts.phase == "await_confirmation" and deadline <= as_of:
        category = 1
    elif facts.evidence_complete and facts.has_human_action:
        category = 2
    elif facts.externally_blocked and facts.business_key is not None:
        category = 3
    else:
        category = 5
    return (
        category,
        deadline,
        facts.lane.value,
        facts.business_key or "",
        facts.scope_kind.value if facts.scope_kind is not None else "",
        facts.work_item_id,
    )


def focus_business_key(
    lane: OperatorLane,
    tasks: Sequence[DiscoveryTask],
    today_entries: Sequence[TodayPriorityFacts],
    *,
    as_of: datetime,
) -> str | None:
    task_entries = sorted(
        (
            entry
            for entry in today_entries
            if entry.lane is lane and entry.business_key is not None
        ),
        key=lambda item: today_priority_key(item, as_of),
    )
    if task_entries:
        return task_entries[0].business_key
    live_tasks = sorted(
        (
            task
            for task in tasks
            if task.lane is lane and task.state is SaleTaskState.CURRENT
        ),
        key=lambda task: (
            task.next_deadline_at or _FAR_FUTURE,
            task.business_key,
            task.task_id,
        ),
    )
    return live_tasks[0].business_key if live_tasks else None


class JczqLaneAdapter:
    lane = OperatorLane.JCZQ

    def validate_slate(self, slate: SaleSlateSnapshot) -> None:
        if slate.lane is not self.lane or not slate.offers:
            raise ValueError("JCZQ slate requires at least one offer")
        _validate_unique_official_order(slate)
        _validate_market_definitions(slate, _JCZQ_MARKET_DEFINITION_IDS)

    def evidence_offer_ids(
        self, slate: SaleSlateSnapshot, as_of: datetime
    ) -> Sequence[str]:
        self.validate_slate(slate)
        return tuple(
            offer.official_offer_revision_id
            for offer in sorted(slate.offers, key=_offer_sort_key)
            if offer_state(offer, as_of) is OfferState.OPEN
        )

    def candidate_inputs(
        self, slate: SaleSlateSnapshot, as_of: datetime
    ) -> CandidateLaneInputs:
        self.validate_slate(slate)
        return _candidate_inputs(slate, _selectable_offers(slate, as_of))

    def result_offer_ids(self, slate: SaleSlateSnapshot) -> Sequence[str]:
        self.validate_slate(slate)
        return tuple(
            offer.official_offer_revision_id
            for offer in sorted(slate.offers, key=_offer_sort_key)
        )


class ZucaiLaneAdapter:
    lane = OperatorLane.ZUCAI

    def validate_slate(self, slate: SaleSlateSnapshot) -> None:
        match_numbers = tuple(offer.official_match_no for offer in slate.offers)
        if slate.lane is not self.lane or len(slate.offers) != 14:
            raise ValueError("Zucai slate requires exactly 14 offers")
        if match_numbers != tuple(str(index) for index in range(1, 15)):
            raise ValueError("Zucai offers must retain official order 1 through 14")
        _validate_market_definitions(slate, _ZUCAI_MARKET_DEFINITION_IDS)

    def evidence_offer_ids(
        self, slate: SaleSlateSnapshot, as_of: datetime
    ) -> Sequence[str]:
        self.validate_slate(slate)
        return tuple(
            offer.official_offer_revision_id for offer in _selectable_offers(slate, as_of)
        )

    def candidate_inputs(
        self, slate: SaleSlateSnapshot, as_of: datetime
    ) -> CandidateLaneInputs:
        self.validate_slate(slate)
        return _candidate_inputs(slate, _selectable_offers(slate, as_of))

    def result_offer_ids(self, slate: SaleSlateSnapshot) -> Sequence[str]:
        self.validate_slate(slate)
        return tuple(
            offer.official_offer_revision_id
            for offer in sorted(slate.offers, key=_offer_sort_key)
        )


def _selectable_offers(
    slate: SaleSlateSnapshot,
    as_of: datetime,
) -> tuple[SaleOfferSnapshot, ...]:
    return tuple(sorted((
        offer
        for offer in slate.offers
        if offer_state(offer, as_of) in {OfferState.UPCOMING, OfferState.OPEN}
    ), key=_offer_sort_key))


def _candidate_inputs(
    slate: SaleSlateSnapshot,
    offers: Sequence[SaleOfferSnapshot],
) -> CandidateLaneInputs:
    return CandidateLaneInputs(
        lane=slate.lane,
        offer_family_ids=tuple(
            offer.official_offer_family_id for offer in offers
        ),
        offer_revision_ids=tuple(
            offer.official_offer_revision_id for offer in offers
        ),
        market_definition_ids=tuple(
            offer.market_definition_ids for offer in offers
        ),
    )


def _validate_market_definitions(
    slate: SaleSlateSnapshot,
    allowed: frozenset[str],
) -> None:
    if any(
        not offer.market_definition_ids
        or not set(offer.market_definition_ids).issubset(allowed)
        for offer in slate.offers
    ):
        raise ValueError(f"invalid {slate.lane.value} market definition")


def _validate_unique_official_order(slate: SaleSlateSnapshot) -> None:
    match_numbers = tuple(offer.official_match_no for offer in slate.offers)
    if len(match_numbers) != len(set(match_numbers)):
        raise ValueError(f"duplicate {slate.lane.value} official order")


__all__ = [
    "CandidateLaneInputs",
    "DiscoveryTask",
    "JczqLaneAdapter",
    "NoTicketClosure",
    "OfferState",
    "OperatorLaneAdapter",
    "SaleSlateAdapter",
    "SaleOfferSnapshot",
    "SaleSlateSnapshot",
    "SaleTaskState",
    "SaleWave",
    "ScopeKind",
    "TodayPriorityFacts",
    "ZucaiLaneAdapter",
    "derive_sale_wave",
    "focus_business_key",
    "offer_state",
    "task_snapshot_hash",
    "task_state",
    "today_priority_key",
]
