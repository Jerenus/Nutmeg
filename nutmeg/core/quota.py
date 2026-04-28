from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable


@dataclass(slots=True, frozen=True)
class QuotaLimit:
    resource: str
    daily_limit: int | None = None
    monthly_limit: int | None = None


@dataclass(slots=True)
class QuotaSnapshot:
    daily_used: int = 0
    monthly_used: int = 0
    limits: dict[str, QuotaLimit] = field(default_factory=dict)

    def check(self, resource: str, cost: int = 1) -> tuple[bool, str | None]:
        limit = self.limits.get(resource)
        if limit is None:
            return True, None
        if limit.daily_limit is not None and self.daily_used + cost > limit.daily_limit:
            return False, f'daily quota exceeded for {resource}'
        if limit.monthly_limit is not None and self.monthly_used + cost > limit.monthly_limit:
            return False, f'monthly quota exceeded for {resource}'
        return True, None


def requires_quota(
    resource: str,
    cost: int = 1,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper

    return decorator
