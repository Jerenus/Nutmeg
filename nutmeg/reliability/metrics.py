"""Bounded process-local telemetry keyed only by allowlisted route templates."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from threading import Lock

RouteKey = tuple[str, str]

DEFAULT_ROUTE_METRIC_ALLOWLIST: frozenset[RouteKey] = frozenset(
    {
        ("GET", "/"),
        ("GET", "/operations"),
        ("GET", "/tickets"),
        ("GET", "/review"),
        ("GET", "/calibration"),
        ("GET", "/ontology"),
        ("GET", "/release"),
        ("GET", "/matches/{match_id}"),
        ("GET", "/lineage/{object_type}/{object_id}"),
        ("GET", "/api/v1/system/health"),
        ("GET", "/api/v1/board"),
        ("GET", "/api/v1/command-center"),
        ("GET", "/api/v1/operations"),
        ("GET", "/api/v1/release"),
        ("GET", "/api/v1/review"),
        ("GET", "/api/v1/calibration"),
        ("GET", "/api/v1/ontology/objects"),
        ("GET", "/api/v1/ontology/objects/{object_type}/{object_id}"),
        ("GET", "/api/v1/scoreboard"),
        ("GET", "/api/v1/alerts"),
        ("GET", "/api/v1/identities"),
        ("GET", "/api/v1/matches/{match_id}"),
        ("GET", "/api/v1/ticket-workbench"),
        ("GET", "/api/v1/ticket-batches/{ticket_batch_id}"),
        ("GET", "/api/v1/ticket-artifacts/{ticket_artifact_id}"),
        ("POST", "/api/v1/ticket-batches"),
        ("POST", "/api/v1/ticket-batches/{ticket_batch_id}/remove-leg"),
        ("POST", "/api/v1/ticket-batches/{ticket_batch_id}/approve"),
        ("POST", "/api/v1/ticket-artifacts/{ticket_artifact_id}/confirmations"),
        ("POST", "/api/v1/ticket-artifacts/{ticket_artifact_id}/confirm"),
        ("GET", "/api/v1/lineage/{object_type}/{object_id}"),
        ("GET", "/api/v1/actions"),
        ("POST", "/api/v1/actions"),
        ("POST", "/api/v1/matches/{match_id}/copilot"),
        ("GET", "/api/v1/events"),
        ("GET", "/api/v1/events/stream"),
    }
)


@dataclass(frozen=True, slots=True)
class RouteMetricSnapshot:
    method: str
    route_template: str
    request_count: int
    error_count: int
    p95_ms: float


@dataclass(slots=True)
class _RouteBucket:
    durations_ms: deque[float]
    request_count: int = 0
    error_count: int = 0


class RouteMetricsRegistry:
    """Retain bounded latency samples without retaining request-derived strings."""

    def __init__(
        self,
        *,
        allowed_routes: set[RouteKey] | frozenset[RouteKey] | None = None,
        max_samples: int = 512,
    ) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be positive")
        configured = allowed_routes or DEFAULT_ROUTE_METRIC_ALLOWLIST
        self._allowed_routes = frozenset(
            (method.upper(), route_template)
            for method, route_template in configured
        )
        self._max_samples = max_samples
        self._buckets: dict[RouteKey, _RouteBucket] = {}
        self._lock = Lock()

    def record(
        self,
        *,
        method: str,
        route_template: str,
        duration_ns: int,
        status_code: int,
        failed: bool = False,
    ) -> bool:
        key = (method.upper(), route_template)
        if key not in self._allowed_routes:
            return False
        duration_ms = max(0.0, duration_ns / 1_000_000)
        with self._lock:
            bucket = self._buckets.setdefault(
                key,
                _RouteBucket(deque(maxlen=self._max_samples)),
            )
            bucket.request_count += 1
            if failed or status_code >= 500:
                bucket.error_count += 1
            bucket.durations_ms.append(duration_ms)
        return True

    def snapshot(self) -> tuple[RouteMetricSnapshot, ...]:
        with self._lock:
            rows = []
            for (method, route_template), bucket in sorted(self._buckets.items()):
                durations = sorted(bucket.durations_ms)
                index = max(0, math.ceil(0.95 * len(durations)) - 1)
                rows.append(
                    RouteMetricSnapshot(
                        method=method,
                        route_template=route_template,
                        request_count=bucket.request_count,
                        error_count=bucket.error_count,
                        p95_ms=round(durations[index], 3),
                    )
                )
            return tuple(rows)

    def retained_sample_count(self, method: str, route_template: str) -> int:
        key = (method.upper(), route_template)
        with self._lock:
            bucket = self._buckets.get(key)
            return len(bucket.durations_ms) if bucket is not None else 0
