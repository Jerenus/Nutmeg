from __future__ import annotations
from nutmeg.services.psychology.jczq_adapter import apply_final_scheme_to_combination, combination_to_data_scheme
from nutmeg.services.psychology.schemas import FinalLeg, FinalScheme

def _stub_combination():
    from types import SimpleNamespace
    leg = SimpleNamespace(match_no="周二001", league="UCL", match_date="2026-04-28", match_time="21:00", home_team="PSG", away_team="Bayern", play="HHAD", pick="home_win", odds=2.10, goal_line="", odds_update="13:01")
    return SimpleNamespace(name="A", risk="low", legs=[leg])

def test_combination_to_data_scheme_maps_pick_to_outcome() -> None:
    scheme = combination_to_data_scheme(_stub_combination())
    assert scheme.legs[0].fixture_id == "周二001:PSG:Bayern"
    assert scheme.legs[0].market == "HHAD"
    assert scheme.legs[0].outcome == "home_win"
    assert scheme.legs[0].odds == 2.10

def test_apply_final_scheme_replaces_pick_when_overridden() -> None:
    combo = _stub_combination()
    final = FinalScheme(legs=[FinalLeg("L1","周二001:PSG:Bayern","HHAD","away_win",2.45,"psychology")], confidence="medium", notes=[])
    updated = apply_final_scheme_to_combination(combo, final)
    assert updated.legs[0].pick == "away_win"
    assert updated.legs[0].odds == 2.45
