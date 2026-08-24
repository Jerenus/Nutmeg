from nutmeg.reliability.metrics import RouteMetricsRegistry

MATCH_ROUTE = ("GET", "/api/v1/matches/{match_id}")


def test_route_metrics_are_bounded_and_compute_count_errors_and_p95() -> None:
    registry = RouteMetricsRegistry(allowed_routes={MATCH_ROUTE}, max_samples=3)

    for duration_ms, status_code in (
        (1.0, 200),
        (2.0, 500),
        (3.0, 503),
        (4.0, 200),
    ):
        registry.record(
            method="GET",
            route_template="/api/v1/matches/{match_id}",
            duration_ns=int(duration_ms * 1_000_000),
            status_code=status_code,
        )

    metric = registry.snapshot()[0]
    assert metric.method == "GET"
    assert metric.route_template == "/api/v1/matches/{match_id}"
    assert metric.request_count == 4
    assert metric.error_count == 2
    assert metric.p95_ms == 4.0
    assert registry.retained_sample_count(*MATCH_ROUTE) == 3


def test_route_metrics_ignore_raw_urls_queries_and_non_allowlisted_routes() -> None:
    registry = RouteMetricsRegistry(allowed_routes={MATCH_ROUTE})

    assert registry.record(
        method="GET",
        route_template="/api/v1/matches/match-secret?token=private",
        duration_ns=1_000_000,
        status_code=200,
    ) is False
    assert registry.record(
        method="POST",
        route_template="/api/v1/matches/{match_id}",
        duration_ns=1_000_000,
        status_code=200,
    ) is False

    assert registry.snapshot() == ()


def test_route_metrics_reset_with_each_registry_process_instance() -> None:
    first = RouteMetricsRegistry(allowed_routes={MATCH_ROUTE})
    first.record(
        method="GET",
        route_template="/api/v1/matches/{match_id}",
        duration_ns=1_000_000,
        status_code=200,
    )

    restarted = RouteMetricsRegistry(allowed_routes={MATCH_ROUTE})

    assert len(first.snapshot()) == 1
    assert restarted.snapshot() == ()
