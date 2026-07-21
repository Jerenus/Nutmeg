from nutmeg.analytics.attribution import CONFOUNDED, attribute_factors
from nutmeg.analytics.scoring import brier

PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
Y = {"home": 1.0, "draw": 0.0, "away": 0.0}


def test_single_factor_is_whole_gain() -> None:
    belief = {"home": 0.6, "draw": 0.25, "away": 0.15}
    factors = [("f1", {"home": 0.1, "draw": -0.05, "away": -0.05})]
    result = attribute_factors(PRIOR, belief, factors, Y)
    assert abs(result["f1"] - (brier(PRIOR, Y) - brier(belief, Y))) < 1e-12


def test_two_factors_sum_to_gain() -> None:
    factors = [
        ("a", {"home": 0.1, "draw": -0.05, "away": -0.05}),
        ("b", {"home": 0.05, "draw": -0.025, "away": -0.025}),
    ]
    belief = {"home": 0.65, "draw": 0.225, "away": 0.125}
    result = attribute_factors(PRIOR, belief, factors, Y)
    total = brier(PRIOR, Y) - brier(belief, Y)
    assert set(result) == {"a", "b"}
    assert abs(sum(result.values()) - total) < 1e-12


def test_off_simplex_is_confounded() -> None:
    factors = [
        ("a", {"home": 0.6, "draw": -0.3, "away": -0.3}),   # prior+a -> home 1.1 (off simplex)
        ("b", {"home": -0.6, "draw": 0.3, "away": 0.3}),
    ]
    belief = dict(PRIOR)
    assert attribute_factors(PRIOR, belief, factors, Y) is CONFOUNDED
