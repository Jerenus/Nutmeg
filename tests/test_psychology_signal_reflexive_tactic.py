from __future__ import annotations

from nutmeg.services.psychology.engine import ReflexiveTacticSignal, SignalContext
from nutmeg.services.psychology.io import FakeLLMCompleter


def test_emits_reading_when_snapshot_present() -> None:
    fixtures = [{"id": "f1", "home_team_name": "PSG", "away_team_name": "Bayern"}]
    snapshots = {"f1": {"home_shape": "4-3-3 high press", "away_shape": "3-4-2-1 mid-block"}}
    sig = ReflexiveTacticSignal(
        llm=FakeLLMCompleter(
            responses=[
                '{"second_order_pick":"away_win","conviction":0.7,'
                '"reasoning":["Kompany inverts to compact 5"]}'
            ]
        )
    )
    [r] = sig.evaluate(
        SignalContext(date="2026-04-29", fixtures=fixtures, snapshots=snapshots, odds={})
    )
    assert r.outcome_view == "away_win"
    assert r.conviction == 0.7
    assert r.evidence


def test_missing_snapshot_abstains() -> None:
    sig = ReflexiveTacticSignal(llm=FakeLLMCompleter(responses=[]))
    [r] = sig.evaluate(
        SignalContext(
            date="2026-04-29",
            fixtures=[{"id": "f1", "home_team_name": "PSG", "away_team_name": "Bayern"}],
            snapshots={},
            odds={},
        )
    )
    assert r.outcome_view is None
    assert "snapshot" in (r.abstain_reason or "")


def test_llm_failure_abstains() -> None:
    sig = ReflexiveTacticSignal(llm=FakeLLMCompleter(responses=["{not valid"]))
    [r] = sig.evaluate(
        SignalContext(
            date="2026-04-29",
            fixtures=[{"id": "f1", "home_team_name": "PSG", "away_team_name": "Bayern"}],
            snapshots={"f1": {"home_shape": "x", "away_shape": "y"}},
            odds={},
        )
    )
    assert r.outcome_view is None
    assert "parse" in (r.abstain_reason or "")


def test_invalid_pick_abstains() -> None:
    sig = ReflexiveTacticSignal(
        llm=FakeLLMCompleter(
            responses=['{"second_order_pick":"weird","conviction":0.9,"reasoning":[]}']
        )
    )
    [r] = sig.evaluate(
        SignalContext(
            date="2026-04-29",
            fixtures=[{"id": "f1", "home_team_name": "PSG", "away_team_name": "Bayern"}],
            snapshots={"f1": {"home_shape": "x", "away_shape": "y"}},
            odds={},
        )
    )
    assert r.outcome_view is None
