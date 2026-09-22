import importlib.util
from pathlib import Path

_PATH = Path(__file__).parents[2] / "experiments" / "team_strength.py"
_SPEC = importlib.util.spec_from_file_location("team_strength", _PATH)
assert _SPEC and _SPEC.loader
team_strength = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(team_strength)


def _match(day, home, away, actual, ph=0.5, pd=0.3, pa=0.2, gh=1, ga=0):
    return dict(
        date=day, league="L", home=home, away=away, gh=gh, ga=ga, actual=actual,
        fair={"home": ph, "draw": pd, "away": pa}, source="jczq",
    )


def test_team_index_measures_points_against_market_expectation():
    matches = [
        _match("2026-07-01", "A", "B", "3"),  # A home win, expected 3*.5+.3 = 1.8 → +1.2
        _match("2026-07-05", "B", "A", "1"),  # draw: B expected 1.8 (−0.8), A expected 0.9 (+0.1)
    ]
    index = team_strength.team_index(matches, since="2026-07-01", min_n=1)
    assert index["A"]["pts"] == 4 and index["A"]["record"] == "1-1-0"
    assert index["A"]["market_expected_pts"] == 2.7
    assert index["A"]["resid_per_match"] == 0.65
    assert index["A"]["resid_shrunk"] == round(0.65 * 2 / 7, 3)
    # B: away loss expected 3*.2+.3 = 0.9 (−0.9), home draw expected 1.8 (−0.8)
    assert index["B"]["resid_per_match"] == round((-0.9 + -0.8) / 2, 3)
    assert index["A"]["home_resid"] == 1.2 and index["A"]["away_resid"] == 0.1


def test_prematch_rows_use_only_matches_strictly_before_kickoff_day():
    matches = [
        _match("2026-07-01", "A", "B", "3"),
        _match("2026-07-03", "C", "A", "0"),  # A wins away (+2.1 for A)
        _match("2026-07-03", "B", "D", "3"),  # same day as above: must not leak into each other
        _match("2026-07-10", "A", "B", "1"),
    ]
    built = team_strength.prematch_rows(matches, since="2026-07-01")
    rows = {(r["date"], r["home"]): r for r in built}
    first = rows[("2026-07-01", "A")]
    assert first["factor"] is None and first["n_hist"] == 0
    same_day = rows[("2026-07-03", "C")]
    assert same_day["n_hist"] == 0  # C has no history; A's 07-01 match counts but min() is C's 0
    last = rows[("2026-07-10", "A")]
    # A: +1.2 (07-01), +2.1 (07-03) → mean 1.65 ; B: −0.9 (07-01), +1.2 (07-03) → mean 0.15
    assert last["n_hist"] == 2
    assert round(last["factor"], 3) == round(1.65 - 0.15, 3)
    assert last["face_hit"] == 0 and last["fair"] == 0.5
    assert last["provably_prospective"] is True
