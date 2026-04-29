from __future__ import annotations

from nutmeg.services.psychology.signals.base import SignalContext
from nutmeg.services.psychology.signals.tournament_stage import TournamentStageSignal


def _ctx(fixtures: list[dict]) -> SignalContext:
    return SignalContext(date="2026-04-29", fixtures=fixtures, snapshots={}, odds={})


def test_first_leg_ucl_knockout_leans_draw_under() -> None:
    fixtures = [
        {
            "id": "psg-bay",
            "competition_code": "UCL",
            "stage": "knockout",
            "leg": 1,
            "tier_home": 1,
            "tier_away": 1,
            "aggregate_score_diff": None,
        }
    ]
    readings = TournamentStageSignal().evaluate(_ctx(fixtures))
    rules = [r for r in readings if r.fixture_id == "psg-bay"]
    assert any(r.market == "HHAD" and r.outcome_view == "draw" for r in rules)
    assert any(r.market == "TTG" and r.outcome_view == "under_2_5" for r in rules)
    for r in rules:
        if r.outcome_view is not None:
            assert r.conviction >= 0.6


def test_second_leg_aggregate_tied_leans_home_over() -> None:
    fixtures = [
        {
            "id": "f2",
            "competition_code": "UEL",
            "stage": "knockout",
            "leg": 2,
            "tier_home": 1,
            "tier_away": 1,
            "aggregate_score_diff": 0,
        }
    ]
    readings = TournamentStageSignal().evaluate(_ctx(fixtures))
    home = [r for r in readings if r.market == "HHAD" and r.outcome_view == "home_win"]
    assert home and home[0].conviction >= 0.5


def test_no_matching_rule_yields_abstain() -> None:
    fixtures = [
        {
            "id": "f3",
            "competition_code": "PL",
            "stage": "regular",
            "leg": None,
            "tier_home": 1,
            "tier_away": 1,
            "aggregate_score_diff": None,
        }
    ]
    readings = TournamentStageSignal().evaluate(_ctx(fixtures))
    abstains = [r for r in readings if r.outcome_view is None]
    assert len(abstains) == len(readings) >= 1
    assert all(r.abstain_reason for r in abstains)


def test_signal_name_constant() -> None:
    assert TournamentStageSignal().name == "tournament_stage"
