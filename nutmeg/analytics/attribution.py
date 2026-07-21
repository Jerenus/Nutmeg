"""Pure factor attribution: split a forecast's skill gain fairly across its factors.

A single-factor revision gets the whole paired Brier gain. A multi-factor revision
uses Shapley values over factor-delta subsets so the joint gain is split fairly and
sums back to the whole (efficiency). If **any** subset's intermediate distribution
leaves the probability simplex, the attribution refuses to fabricate credit and
returns the ``CONFOUNDED`` sentinel — that revision feeds no factor estimate.
"""
from __future__ import annotations

from itertools import combinations
from math import factorial

from nutmeg.analytics.scoring import brier

CONFOUNDED = object()

_TOL = 1e-9


def _subset_distribution(
    prior: dict[str, float], factors: list[tuple[str, dict[str, float]]], indices: tuple[int, ...]
) -> dict[str, float]:
    distribution = dict(prior)
    for index in indices:
        for key, delta in factors[index][1].items():
            distribution[key] = distribution.get(key, 0.0) + delta
    return distribution


def _on_simplex(distribution: dict[str, float]) -> bool:
    return all(-_TOL <= value <= 1 + _TOL for value in distribution.values())


def _attribute(
    prior: dict[str, float],
    factors: list[tuple[str, dict[str, float]]],
    reference: dict[str, float],
) -> dict[str, float] | object:
    n = len(factors)
    if n == 0:
        return {}
    base = brier(prior, reference)
    value: dict[tuple[int, ...], float] = {}
    for size in range(n + 1):
        for subset in combinations(range(n), size):
            distribution = _subset_distribution(prior, factors, subset)
            if not _on_simplex(distribution):
                return CONFOUNDED
            value[subset] = base - brier(distribution, reference)

    contributions: dict[str, float] = {}
    for i in range(n):
        others = [j for j in range(n) if j != i]
        phi = 0.0
        for size in range(len(others) + 1):
            weight = factorial(size) * factorial(n - size - 1) / factorial(n)
            for subset in combinations(others, size):
                with_i = tuple(sorted((*subset, i)))
                phi += weight * (value[with_i] - value[subset])
        contributions[factors[i][0]] = phi
    return contributions


def attribute_factors(
    prior: dict[str, float],
    belief: dict[str, float],
    factors: list[tuple[str, dict[str, float]]],
    y: dict[str, float],
) -> dict[str, float] | object:
    return _attribute(prior, factors, y)


def attribute_closing(
    prior: dict[str, float],
    belief: dict[str, float],
    factors: list[tuple[str, dict[str, float]]],
    c: dict[str, float],
) -> dict[str, float] | object:
    return _attribute(prior, factors, c)
