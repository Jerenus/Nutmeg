from __future__ import annotations

from unittest.mock import MagicMock

from nutmeg.services.psychology.engine import PsychologyEngine
from nutmeg.services.psychology.schemas import SignalReading
from nutmeg.services.psychology.signals.base import SignalContext


def _reading(
    provider: str,
    fixture: str,
    market: str,
    outcome: str | None,
    conv: float,
    abstain: str | None = None,
) -> SignalReading:
    return SignalReading(provider, fixture, market, outcome, conv, [], [], abstain)


def test_aggregates_agreeing_signals() -> None:
    p1 = MagicMock()
    p1.name = "tournament_stage"
    p1.evaluate.return_value = [_reading("tournament_stage", "f1", "HHAD", "away_win", 0.65)]
    p2 = MagicMock()
    p2.name = "contrarian_narrative"
    p2.evaluate.return_value = [_reading("contrarian_narrative", "f1", "HHAD", "away_win", 0.7)]
    [v] = PsychologyEngine(providers=[p1, p2]).evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id": "f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "home_win"}},
    )
    assert v.market_views["HHAD"].outcome == "away_win"
    assert 0.65 <= v.market_views["HHAD"].conviction <= 0.95
    assert v.lean_direction == "diverge_data"


def test_disagreeing_signals_pick_highest_conviction() -> None:
    p1 = MagicMock()
    p1.name = "a"
    p1.evaluate.return_value = [_reading("a", "f1", "HHAD", "home_win", 0.6)]
    p2 = MagicMock()
    p2.name = "b"
    p2.evaluate.return_value = [_reading("b", "f1", "HHAD", "away_win", 0.8)]
    [v] = PsychologyEngine(providers=[p1, p2]).evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id": "f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "draw"}},
    )
    assert v.market_views["HHAD"].outcome == "away_win"
    assert v.market_views["HHAD"].conviction == 0.8


def test_all_abstain_neutral() -> None:
    p = MagicMock()
    p.name = "p"
    p.evaluate.return_value = [_reading("p", "f1", "HHAD", None, 0.0, abstain="x")]
    [v] = PsychologyEngine(providers=[p]).evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id": "f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "draw"}},
    )
    assert v.market_views == {} or all(view.outcome == "" for view in v.market_views.values())
    assert v.lean_direction == "neutral"
    assert v.conviction == 0.0


def test_provider_crash_isolated() -> None:
    p1 = MagicMock()
    p1.name = "good"
    p1.evaluate.return_value = [_reading("good", "f1", "HHAD", "home_win", 0.7)]
    p2 = MagicMock()
    p2.name = "bad"
    p2.evaluate.side_effect = RuntimeError("boom")
    [v] = PsychologyEngine(providers=[p1, p2]).evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id": "f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "draw"}},
    )
    crash_readings = [r for r in v.contributing_readings if r.provider == "bad"]
    assert crash_readings and (crash_readings[0].abstain_reason or "").startswith(
        "provider_crashed"
    )


def test_agreement_with_data_pick() -> None:
    p = MagicMock()
    p.name = "p"
    p.evaluate.return_value = [_reading("p", "f1", "HHAD", "home_win", 0.7)]
    [v] = PsychologyEngine(providers=[p]).evaluate(
        ctx=SignalContext(date="2026-04-29", fixtures=[{"id": "f1"}], snapshots={}, odds={}),
        data_picks={"f1": {"HHAD": "home_win"}},
    )
    assert v.lean_direction == "agree_data"
