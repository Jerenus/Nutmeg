"""Pure probability-distribution and factor-delta validation.

A belief/prior distribution lives on the probability simplex (non-negative,
sums to 1). A factor's delta is a signed per-outcome shift summing to zero; the
sum of all factor deltas must reconstruct ``belief − prior`` exactly. These
checks are the invariant the forecast validator enforces before any commit.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

_TOL = 1e-6

Distribution = Mapping[str, float]


def is_normalized(distribution: Distribution, tol: float = _TOL) -> bool:
    if abs(sum(distribution.values()) - 1.0) > tol:
        return False
    return all(-tol <= value <= 1.0 + tol for value in distribution.values())


def validate_simplex(distribution: Distribution, tol: float = _TOL) -> None:
    if any(value < -tol for value in distribution.values()):
        raise ValueError('distribution has a negative probability')
    if abs(sum(distribution.values()) - 1.0) > tol:
        raise ValueError('distribution does not sum to 1')


def delta_from(prior: Distribution, belief: Distribution) -> dict[str, float]:
    keys = set(prior) | set(belief)
    return {key: belief.get(key, 0.0) - prior.get(key, 0.0) for key in keys}


def reconstructs_belief(
    prior: Distribution,
    deltas: Sequence[Distribution],
    belief: Distribution,
    tol: float = _TOL,
) -> bool:
    # Each factor delta must be outcome-neutral (sum to zero).
    for delta in deltas:
        if abs(sum(delta.values())) > tol:
            return False
    keys = set(prior) | set(belief)
    for delta in deltas:
        keys |= set(delta)
    for key in keys:
        combined = prior.get(key, 0.0) + sum(delta.get(key, 0.0) for delta in deltas)
        if abs(combined - belief.get(key, 0.0)) > tol:
            return False
    return True
