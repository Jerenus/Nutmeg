import pytest

from nutmeg.ontology.decision.distributions import (
    delta_from,
    is_normalized,
    reconstructs_belief,
    validate_simplex,
)


def test_normalization_and_reconstruction() -> None:
    prior = {"home": 0.5, "draw": 0.3, "away": 0.2}
    belief = {"home": 0.6, "draw": 0.25, "away": 0.15}
    d = delta_from(prior, belief)
    assert abs(sum(d.values())) < 1e-9          # deltas sum to zero
    assert reconstructs_belief(prior, [d], belief)
    assert is_normalized(belief)
    assert not is_normalized({"home": 0.6, "draw": 0.6, "away": 0.6})


def test_reconstruct_rejects_wrong_delta_sum() -> None:
    prior = {"home": 0.5, "draw": 0.3, "away": 0.2}
    belief = {"home": 0.6, "draw": 0.25, "away": 0.15}
    wrong = {"home": 0.2, "draw": 0.0, "away": 0.0}   # does not reach belief, sum != 0
    assert not reconstructs_belief(prior, [wrong], belief)


def test_two_factors_that_sum_to_belief_minus_prior() -> None:
    prior = {"home": 0.5, "draw": 0.3, "away": 0.2}
    belief = {"home": 0.6, "draw": 0.25, "away": 0.15}
    f1 = {"home": 0.06, "draw": -0.03, "away": -0.03}
    f2 = {"home": 0.04, "draw": -0.02, "away": -0.02}
    assert reconstructs_belief(prior, [f1, f2], belief)


def test_validate_simplex_rejects_negative_or_unnormalized() -> None:
    with pytest.raises(ValueError):
        validate_simplex({"home": 1.2, "draw": -0.2, "away": 0.0})
    with pytest.raises(ValueError):
        validate_simplex({"home": 0.5, "draw": 0.3, "away": 0.4})   # sums to 1.2
