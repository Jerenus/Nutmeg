"""Pure budget validation.

The ¥400 total cap and per-bucket caps are a *ceiling*, not a fill target: an empty
legs list is always valid. A ticket that exceeds the total or any bucket cap is
rejected before it can be written.
"""
from __future__ import annotations

from collections.abc import Sequence

_TOL = 1e-9


def validate_within_budget(
    total_cap: float,
    bucket_caps: dict[str, float],
    legs: Sequence[dict[str, object]],
) -> None:
    total = sum(float(leg['stake']) for leg in legs)
    if total > total_cap + _TOL:
        raise ValueError(f'total stake {total} exceeds cap {total_cap}')
    by_bucket: dict[str, float] = {}
    for leg in legs:
        bucket = str(leg['bucket'])
        by_bucket[bucket] = by_bucket.get(bucket, 0.0) + float(leg['stake'])
    for bucket, amount in by_bucket.items():
        cap = bucket_caps.get(bucket)
        if cap is not None and amount > cap + _TOL:
            raise ValueError(f'bucket {bucket} stake {amount} exceeds cap {cap}')
