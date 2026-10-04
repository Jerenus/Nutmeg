
from nutmeg.analytics.scoring import brier, brier_skill, closing_skill_delta, directional_alignment


def test_brier_perfect_and_worst() -> None:
    perfect = {"home": 1.0, "draw": 0.0, "away": 0.0}
    assert brier(perfect, perfect) == 0.0
    assert brier({"home": 0.0, "draw": 0.0, "away": 1.0}, perfect) == 2.0


def test_brier_skill_and_zero_denominator() -> None:
    assert brier_skill([0.2], [0.5]) == 1 - 0.2 / 0.5
    assert brier_skill([0.0], [0.0]) is None


def test_closing_and_directional() -> None:
    q = {"home": 0.6, "draw": 0.25, "away": 0.15}
    p = {"home": 0.5, "draw": 0.3, "away": 0.2}
    c = {"home": 0.62, "draw": 0.24, "away": 0.14}
    assert closing_skill_delta(q, p, c) < 0
    assert directional_alignment(q, p, c) > 0


