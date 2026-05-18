"""Recording value-engine conflicts into the conflict store (Phase 3 piece 3).

``record_conflict_signals`` runs the value bridge over the day's matches,
converts the match_winner conflicts to ``CrossCheckSignal`` rows, and persists
them so next-day ``jczq-daily-review`` grades them — closing the
self-validation loop. No network: a fake bridge is injected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.domain.value import ValueCandidate
from nutmeg.services.jczq_conflict_bridge import (
    record_conflict_signals,
    value_report_to_signals,
)
from nutmeg.services.jczq_conflict_store import ConflictStore
from nutmeg.services.jczq_value_bridge import JczqMatchConflicts, JczqValueReport


def _candidate(
    *,
    market_key: str = "match_winner",
    outcome_key: str = "home",
    outcome_name: str = "Home",
    edge: float = 0.12,
    best_odds: float = 2.2,
) -> ValueCandidate:
    return ValueCandidate(
        fixture_id="1379305",
        kickoff_at=datetime(2026, 5, 17, 14, 0, tzinfo=UTC),
        home_team="Arsenal",
        away_team="Tottenham",
        outcome_key=outcome_key,
        outcome_name=outcome_name,
        model_probability=0.55,
        market_probability=0.43,
        edge=edge,
        best_odds=best_odds,
        expected_value=0.21,
        quarter_kelly_fraction=0.03,
        rating="strong",
        model_name="dixon-coles-lite",
        market_key=market_key,
    )


def _report(*conflicts: ValueCandidate, match_no: str = "周六001") -> JczqValueReport:
    return JczqValueReport(
        matches=[
            JczqMatchConflicts(
                match_no=match_no,
                league="英超",
                home_team="阿森纳",
                away_team="热刺",
                aligned=True,
                fixture_id="1379305",
                conflicts=list(conflicts),
            )
        ]
    )


class _FakeBridge:
    def __init__(self, report: JczqValueReport) -> None:
        self._report = report
        self.evaluated: list[JczqDailyMatch] | None = None

    def evaluate_day(self, matches: list[JczqDailyMatch]) -> JczqValueReport:
        self.evaluated = list(matches)
        return self._report


def _match(match_no: str = "周六001") -> JczqDailyMatch:
    return JczqDailyMatch(
        match_no=match_no,
        match_date="2026-05-17",
        match_time="22:00",
        league="英超",
        home_team="阿森纳",
        away_team="热刺",
        status="售卖中",
        hot_direction="主胜",
        role="—",
        confidence_note="",
    )


# --- value_report_to_signals -----------------------------------------------


def test_value_report_to_signals_maps_match_winner_to_had() -> None:
    signals, odds = value_report_to_signals(_report(_candidate()))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.match_no == "周六001"
    assert sig.pool == "had"
    assert sig.pick == "胜"  # home → 胜
    assert abs(sig.delta - 0.12) < 1e-9
    assert abs(odds["周六001"] - 2.2) < 1e-9


def test_value_report_to_signals_keeps_only_match_winner_conflicts() -> None:
    # Grading is had-pool only; ttg/crs/handicap conflicts are not recorded.
    report = _report(
        _candidate(market_key="total_goals", outcome_key="2", outcome_name="2"),
        _candidate(market_key="match_winner", outcome_key="away", outcome_name="Away"),
    )
    signals, odds = value_report_to_signals(report)

    assert [s.pool for s in signals] == ["had"]
    assert signals[0].pick == "负"  # away → 负


def test_value_report_to_signals_takes_best_had_conflict_per_match() -> None:
    # Two match_winner conflicts on one match → only the highest-edge one.
    report = _report(
        _candidate(outcome_key="home", edge=0.05, best_odds=2.0),
        _candidate(outcome_key="draw", outcome_name="Draw", edge=0.15, best_odds=3.4),
    )
    signals, odds = value_report_to_signals(report)

    assert len(signals) == 1
    assert signals[0].pick == "平"  # draw won on edge
    assert abs(odds["周六001"] - 3.4) < 1e-9


def test_value_report_to_signals_skips_unaligned_and_empty() -> None:
    report = JczqValueReport(
        matches=[
            JczqMatchConflicts(
                match_no="周六001",
                league="英超",
                home_team="阿森纳",
                away_team="热刺",
                aligned=False,
                coverage_note="未对齐",
            ),
            JczqMatchConflicts(
                match_no="周六002",
                league="德甲",
                home_team="拜仁",
                away_team="多特",
                aligned=True,
                fixture_id="999",
                conflicts=[],
            ),
        ]
    )
    signals, odds = value_report_to_signals(report)

    assert signals == []
    assert odds == {}


# --- record_conflict_signals -----------------------------------------------


def test_record_conflict_signals_persists_to_store(tmp_path: Path) -> None:
    bridge = _FakeBridge(_report(_candidate()))

    count = record_conflict_signals(
        value_bridge=bridge,
        run_date="2026-05-17",
        output_dir=tmp_path,
        matches=[_match()],
    )

    assert count == 1
    assert bridge.evaluated is not None
    rows = ConflictStore(tmp_path / "memory" / "conflict-signals.json").load()
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-05-17"
    assert rows[0]["match_no"] == "周六001"
    assert rows[0]["pool"] == "had"
    assert rows[0]["pick"] == "胜"
    assert rows[0]["hit"] is None  # ungraded until next-day review


def test_record_conflict_signals_returns_zero_when_no_conflicts(
    tmp_path: Path,
) -> None:
    bridge = _FakeBridge(_report(match_no="周六001"))  # no conflicts

    count = record_conflict_signals(
        value_bridge=bridge,
        run_date="2026-05-17",
        output_dir=tmp_path,
        matches=[_match()],
    )

    assert count == 0
    # No store file created for an empty signal set.
    assert not (tmp_path / "memory" / "conflict-signals.json").exists()


def test_record_conflict_signals_reads_matches_from_context(tmp_path: Path) -> None:
    # When matches are not passed, they come from the run date's context.json
    # (written by build_brief). This is the live CLI path.
    from nutmeg.services.jczq_daily import JczqDailyAdvisorService
    from tests.test_jczq_daily_service import FakeProvider

    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )
    bridge = _FakeBridge(_report(_candidate(), match_no="周五001"))

    count = record_conflict_signals(
        value_bridge=bridge,
        run_date="2026-05-01",
        output_dir=tmp_path,
    )

    assert count == 1
    assert bridge.evaluated is not None
    assert [m.match_no for m in bridge.evaluated] == [
        "周五001",
        "周五003",
        "周五004",
        "周五005",
    ]


def test_record_conflict_signals_returns_zero_when_no_context(tmp_path: Path) -> None:
    # No context.json and no explicit matches → nothing to do, no crash.
    bridge = _FakeBridge(_report(_candidate()))

    count = record_conflict_signals(
        value_bridge=bridge,
        run_date="2026-05-01",
        output_dir=tmp_path,
    )

    assert count == 0


def test_record_conflict_signals_is_idempotent_per_run_date(tmp_path: Path) -> None:
    # Re-running the brief for the same date must not double-record.
    bridge = _FakeBridge(_report(_candidate()))

    record_conflict_signals(
        value_bridge=bridge,
        run_date="2026-05-17",
        output_dir=tmp_path,
        matches=[_match()],
    )
    record_conflict_signals(
        value_bridge=bridge,
        run_date="2026-05-17",
        output_dir=tmp_path,
        matches=[_match()],
    )

    rows = ConflictStore(tmp_path / "memory" / "conflict-signals.json").load()
    assert len(rows) == 1  # second run replaced, not appended
