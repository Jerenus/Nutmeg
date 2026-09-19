from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from nutmeg.product.operator_settlement import (
    JczqLearningCoordinator,
    prospective_eligible,
)


class _ActionService:
    def __init__(self, *, judgment_count: int, review_count: int, settlement_count: int):
        self._judgments = tuple(object() for _ in range(judgment_count))
        self._reviews = tuple(object() for _ in range(review_count))
        self._run = SimpleNamespace(persisted_settlement_count=settlement_count)

    @contextmanager
    def unit_of_work(self):
        yield SimpleNamespace(
            operator_decision=SimpleNamespace(
                current_operator_match_judgments_for_task_family=(
                    lambda _task_family_id: self._judgments
                )
            ),
            operator_review=SimpleNamespace(
                review_items_for_task=lambda _task_family_id: self._reviews
            ),
            operator_result=SimpleNamespace(
                latest_task_settlement_run_for_task_family=(
                    lambda _task_family_id: self._run
                )
            ),
        )


class _ReviewWorker:
    def __init__(self) -> None:
        self.calls = []

    def run_once(self, *, limit, as_of):
        self.calls.append((limit, as_of))
        return (object(),)


def test_prospective_eligibility_requires_prefix_visibility_and_live_mode() -> None:
    kickoff = datetime(2026, 9, 19, 12, tzinfo=UTC)

    assert prospective_eligible(
        captured_at=datetime(2026, 9, 19, 11, 59, tzinfo=UTC),
        kickoff_at=kickoff,
        historical_replay=False,
    )
    assert not prospective_eligible(
        captured_at=kickoff,
        kickoff_at=kickoff,
        historical_replay=False,
    )
    assert not prospective_eligible(
        captured_at=datetime(2026, 9, 19, 11, 59, tzinfo=UTC),
        kickoff_at=kickoff,
        historical_replay=True,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        prospective_eligible(
            captured_at=datetime(2026, 9, 19, 11, 59),
            kickoff_at=kickoff,
            historical_replay=False,
        )


def test_no_ticket_still_projects_forecast_truth_without_money() -> None:
    service = _ActionService(judgment_count=30, review_count=1, settlement_count=9)
    worker = _ReviewWorker()
    rsi_calls = []
    coordinator = JczqLearningCoordinator(
        service,
        terminal_resolver=lambda _day: SimpleNamespace(kind="no_ticket"),
        review_worker=worker,
        rsi_after_settle=lambda **kwargs: rsi_calls.append(kwargs) or {"F9": "not_due"},
        clock=lambda: datetime(2026, 9, 20, tzinfo=UTC),
    )

    result = coordinator.settle_and_project("2026-09-19", historical_replay=False)

    assert result.money_settlement_count == 0
    assert result.forecast_grade_count == 30
    assert result.review_materialization_count == 1
    assert result.rsi_projection == {"F9": "not_due"}
    assert result.gaps == ()
    assert len(worker.calls) == 1
    assert rsi_calls[0]["day"] == "2026-09-19"


def test_historical_replay_never_projects_prospective_rsi() -> None:
    service = _ActionService(judgment_count=30, review_count=1, settlement_count=2)
    rsi_calls = []
    coordinator = JczqLearningCoordinator(
        service,
        terminal_resolver=lambda _day: SimpleNamespace(kind="selected"),
        review_worker=_ReviewWorker(),
        rsi_after_settle=lambda **kwargs: rsi_calls.append(kwargs) or {},
        clock=lambda: datetime(2026, 9, 20, tzinfo=UTC),
    )

    result = coordinator.settle_and_project("2026-09-19", historical_replay=True)

    assert result.money_settlement_count == 2
    assert result.forecast_grade_count == 30
    assert result.rsi_projection == {}
    assert rsi_calls == []


def test_missing_outcomes_leave_an_explicit_learning_gap() -> None:
    service = _ActionService(judgment_count=30, review_count=0, settlement_count=0)
    coordinator = JczqLearningCoordinator(
        service,
        terminal_resolver=lambda _day: SimpleNamespace(kind="no_ticket"),
        review_worker=_ReviewWorker(),
        rsi_after_settle=lambda **_kwargs: {},
        clock=lambda: datetime(2026, 9, 20, tzinfo=UTC),
    )

    result = coordinator.settle_and_project("2026-09-19", historical_replay=False)

    assert result.forecast_grade_count == 0
    assert result.gaps == ("forecast_truth_review_not_materialized",)
