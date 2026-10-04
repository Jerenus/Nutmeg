"""Pure, versioned scoring primitives (design §2.2).

Every metric is a pure function of its distribution arguments — no clock, no state —
so a projection built at a fixed high-watermark reproduces byte-identical scores.
Distributions are ``{outcome_key: probability}`` dicts; a one-hot outcome uses the
same keys. A metric whose inputs are missing is excluded by the caller from that
metric's denominator — it is never silently counted as zero.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

metric_version = 'scoring-v1'


def _keys(*distributions: dict[str, float]) -> list[str]:
    seen: dict[str, None] = {}
    for distribution in distributions:
        for key in distribution:
            seen.setdefault(key, None)
    return list(seen)


def brier(q: dict[str, float], y: dict[str, float]) -> float:
    return sum((q.get(k, 0.0) - y.get(k, 0.0)) ** 2 for k in _keys(q, y))


def brier_skill(scores: Sequence[float], prior_scores: Sequence[float]) -> float | None:
    denominator = sum(prior_scores)
    if denominator == 0:
        return None   # prior Brier is 0 — skill is unavailable, never divide by zero
    return 1 - sum(scores) / denominator


def log_score(q: dict[str, float], y: dict[str, float], clip: float) -> float:
    outcome_key = next(k for k, value in y.items() if value == 1.0)
    probability = min(max(q.get(outcome_key, 0.0), clip), 1 - clip)
    return -math.log(probability)


def closing_skill_delta(
    q: dict[str, float], p: dict[str, float], c: dict[str, float]
) -> float:
    return brier(q, c) - brier(p, c)


def directional_alignment(
    q: dict[str, float], p: dict[str, float], c: dict[str, float]
) -> float:
    return sum(
        (q.get(k, 0.0) - p.get(k, 0.0)) * (c.get(k, 0.0) - p.get(k, 0.0))
        for k in _keys(q, p, c)
    )


