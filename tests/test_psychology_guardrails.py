from __future__ import annotations

from nutmeg.services.psychology.engine import BudgetGuard, ConvictionGate
from nutmeg.services.psychology.schemas import OverrideCandidate


def _candidate(
    leg_id: str, conviction: float, provider: str = "tournament_stage"
) -> OverrideCandidate:
    return OverrideCandidate(
        leg_id=leg_id,
        fixture_id="f" + leg_id,
        market="HHAD",
        from_outcome="home_win",
        to_outcome="away_win",
        conviction=conviction,
        reasoning=[],
        source_provider=provider,
    )


def test_conviction_gate_filters_below_threshold() -> None:
    accepted, rejected = ConvictionGate(threshold=0.7).apply(
        [_candidate("1", 0.65), _candidate("2", 0.72)]
    )
    assert [c.leg_id for c in accepted] == ["2"]
    assert rejected[0][1].startswith("below_conviction")


def test_budget_guard_caps_to_one() -> None:
    accepted, rejected = BudgetGuard(max_reversals=1).apply(
        [_candidate("1", 0.8), _candidate("2", 0.9)]
    )
    assert len(accepted) == 1
    assert accepted[0].leg_id == "2"
    assert rejected[0][1] == "budget_exhausted"


def test_budget_guard_zero_rejects_all() -> None:
    accepted, rejected = BudgetGuard(max_reversals=0).apply([_candidate("1", 0.9)])
    assert accepted == []
    assert rejected[0][1] == "budget_exhausted"


def test_conviction_gate_threshold_inclusive() -> None:
    accepted, rejected = ConvictionGate(threshold=0.7).apply([_candidate("1", 0.7)])
    assert len(accepted) == 1
