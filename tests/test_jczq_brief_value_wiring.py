"""build_brief ↔ value bridge wiring (Phase 3 piece 2).

Exercises the optional ``value_bridge`` hook on ``build_brief``: when a bridge
is supplied the brief invokes it over the day's JCZQ matches and renders the
real 赔率冲突点 section; when it is absent — or the bridge degrades — the brief
still renders with the placeholder. No network: a fake bridge is injected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.domain.value import ValueCandidate
from nutmeg.services.jczq_brief import build_brief
from nutmeg.services.jczq_daily import JczqDailyAdvisorService
from nutmeg.services.jczq_value_bridge import JczqMatchConflicts, JczqValueReport
from tests.test_jczq_daily_service import FakeProvider


class _FakeBridge:
    """Records the matches it was asked to evaluate; returns a fixed report."""

    def __init__(self, report: JczqValueReport) -> None:
        self._report = report
        self.evaluated_matches: list[JczqDailyMatch] | None = None

    def evaluate_day(self, matches: list[JczqDailyMatch]) -> JczqValueReport:
        self.evaluated_matches = list(matches)
        return self._report


class _RaisingBridge:
    """A bridge whose evaluate_day blows up — degradation must absorb it."""

    def evaluate_day(self, matches: list[JczqDailyMatch]) -> JczqValueReport:
        raise RuntimeError("api-football unreachable")


def _value_report(match_no: str) -> JczqValueReport:
    candidate = ValueCandidate(
        fixture_id="1379305",
        kickoff_at=datetime(2026, 5, 1, 14, 0, tzinfo=UTC),
        home_team="Arsenal",
        away_team="Tottenham",
        outcome_key="home",
        outcome_name="Home",
        model_probability=0.55,
        market_probability=0.43,
        edge=0.12,
        best_odds=2.2,
        expected_value=0.21,
        quarter_kelly_fraction=0.03,
        rating="strong",
        model_name="dixon-coles-lite",
        market_key="match_winner",
    )
    return JczqValueReport(
        matches=[
            JczqMatchConflicts(
                match_no=match_no,
                league="英超",
                home_team="阿森纳",
                away_team="热刺",
                aligned=True,
                fixture_id="1379305",
                conflicts=[candidate],
            )
        ]
    )


def _seed_context(tmp_path: Path) -> str:
    """Run the advisor once so a replay context.json exists for build_brief."""
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )
    return "2026-05-01"


def test_build_brief_invokes_value_bridge_over_the_day_matches(tmp_path: Path) -> None:
    run_date = _seed_context(tmp_path)
    bridge = _FakeBridge(_value_report("周五001"))

    text = build_brief(
        replay_date=run_date,
        output_dir=tmp_path,
        value_bridge=bridge,
    )

    # The bridge was handed the day's real JCZQ matches.
    assert bridge.evaluated_matches is not None
    assert [m.match_no for m in bridge.evaluated_matches] == [
        "周五001",
        "周五003",
        "周五004",
        "周五005",
    ]
    # And the rendered section carries the real conflict numbers.
    assert "## 赔率冲突点" in text
    assert "+12%" in text
    assert "价值引擎未接线" not in text


def test_build_brief_renders_placeholder_when_no_bridge(tmp_path: Path) -> None:
    run_date = _seed_context(tmp_path)

    text = build_brief(replay_date=run_date, output_dir=tmp_path)

    assert "## 赔率冲突点" in text
    assert "价值引擎未接线" in text


def test_build_brief_degrades_to_placeholder_when_bridge_raises(
    tmp_path: Path,
) -> None:
    run_date = _seed_context(tmp_path)

    # A bridge that explodes must not crash the brief — graceful degradation.
    text = build_brief(
        replay_date=run_date,
        output_dir=tmp_path,
        value_bridge=_RaisingBridge(),
    )

    assert "## 赔率冲突点" in text
    assert "价值引擎未接线" in text
