"""Product-facing settlement exports and JCZQ learning coordination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from nutmeg.ontology.operator.task_settlement import (
    PayoutCashEntryPlan,
    SettlementLegInput,
    SettlementLegPlan,
    SettlementNoteInput,
    SettlementNotePlan,
    SettlementOutcomeInput,
    SettlementTicketInput,
    TicketSettlementPlan,
    ZucaiPrizeTierInput,
    grade_ticket_settlement,
    plan_payout_cash_entries,
)


class _ReviewWorker(Protocol):
    def run_once(self, *, limit: int, as_of: datetime) -> tuple[object, ...]: ...


@dataclass(frozen=True, slots=True)
class JczqLearningProjection:
    business_date: str
    terminal_kind: str
    money_settlement_count: int
    forecast_grade_count: int
    review_materialization_count: int
    rsi_projection: dict[str, str]
    gaps: tuple[str, ...]
    historical_replay: bool


def prospective_eligible(
    *,
    captured_at: datetime,
    kickoff_at: datetime,
    historical_replay: bool,
) -> bool:
    """Return whether an observation may enter a prospective experiment."""
    if captured_at.tzinfo is None or kickoff_at.tzinfo is None:
        raise ValueError("captured_at and kickoff_at must be timezone-aware")
    return not historical_replay and captured_at < kickoff_at


class JczqLearningCoordinator:
    """Project formal settlement/review state into the JCZQ learning surface.

    Result import and money settlement remain owned by their existing Actions. This
    coordinator runs the existing review worker, reports the durable projections,
    and invokes RSI's existing post-settlement Action wiring only for live samples.
    """

    def __init__(
        self,
        action_service,
        *,
        terminal_resolver: Callable[[str], object],
        review_worker: _ReviewWorker,
        rsi_after_settle: Callable[..., dict[str, str]],
        data_dir: str | Path = ".",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._action_service = action_service
        self._terminal_resolver = terminal_resolver
        self._review_worker = review_worker
        self._rsi_after_settle = rsi_after_settle
        self._data_dir = Path(data_dir)
        self._clock = clock or (lambda: datetime.now(UTC))

    def settle_and_project(
        self,
        business_date: str,
        *,
        historical_replay: bool,
        issue: str | None = None,
    ) -> JczqLearningProjection:
        terminal = self._terminal_resolver(business_date)
        materialized = self._review_worker.run_once(limit=100, as_of=self._clock())
        task_family_id = f"jczq:{business_date}"
        with self._action_service.unit_of_work() as uow:
            judgments = (
                uow.operator_decision.current_operator_match_judgments_for_task_family(
                    task_family_id
                )
            )
            reviews = uow.operator_review.review_items_for_task(task_family_id)
            settlement = (
                uow.operator_result.latest_task_settlement_run_for_task_family(
                    task_family_id
                )
            )

        gaps: list[str] = []
        if not reviews:
            gaps.append("forecast_truth_review_not_materialized")
        forecast_grade_count = len(judgments) if reviews else 0
        money_settlement_count = (
            0
            if terminal.kind == "no_ticket" or settlement is None
            else settlement.persisted_settlement_count
        )
        rsi_projection = (
            {}
            if historical_replay
            else self._rsi_after_settle(
                day=business_date,
                issue=issue,
                data_dir=self._data_dir,
            )
        )
        return JczqLearningProjection(
            business_date=business_date,
            terminal_kind=terminal.kind,
            money_settlement_count=money_settlement_count,
            forecast_grade_count=forecast_grade_count,
            review_materialization_count=len(materialized),
            rsi_projection=dict(rsi_projection),
            gaps=tuple(gaps),
            historical_replay=historical_replay,
        )

__all__ = [
    "PayoutCashEntryPlan",
    "SettlementLegInput",
    "SettlementLegPlan",
    "SettlementNoteInput",
    "SettlementNotePlan",
    "SettlementOutcomeInput",
    "SettlementTicketInput",
    "TicketSettlementPlan",
    "ZucaiPrizeTierInput",
    "JczqLearningCoordinator",
    "JczqLearningProjection",
    "grade_ticket_settlement",
    "plan_payout_cash_entries",
    "prospective_eligible",
]
