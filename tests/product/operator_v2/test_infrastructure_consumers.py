from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.product_api import create_product_app
from nutmeg.ontology.actions.artifact_ingest import ArtifactIngestRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel
from nutmeg.product import operator_workers
from nutmeg.product.operator_runtime import (
    OperatorRuntimeConfig,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
)
from nutmeg.product.wiring import build_product_services

NOW = datetime(2026, 9, 5, 10, tzinfo=UTC)


def _kernel_with_events(tmp_path: Path, *, count: int = 2):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data", _env_file=None))
    kernel.initialize()
    for index in range(count):
        outcome = kernel.artifact_ingest.ingest(
            ArtifactIngestRequest(
                content=f"event-{index}".encode(),
                content_type="text/plain",
                source_name="test",
                source_type="fixture",
                actor_id="source:test",
                actor_role=ActorRole.CONNECTOR,
                idempotency_key=f"projection-consumer:{index}",
                retrieved_at=NOW,
            )
        )
        assert outcome.is_success
    return kernel


@pytest.mark.parametrize(
    ("worker_type_name", "consumer_name"),
    [
        ("ProductOutboxWorker", "product_sse_delivery"),
        ("OperatorReadModelInvalidator", "operator_read_model_invalidation"),
    ],
)
def test_projection_consumers_advance_durable_independent_cursors_without_actions(
    tmp_path: Path,
    worker_type_name: str,
    consumer_name: str,
) -> None:
    worker_type = getattr(operator_workers, worker_type_name, None)
    assert worker_type is not None
    kernel = _kernel_with_events(tmp_path)
    worker = worker_type(
        unit_of_work_factory=lambda: OntologyUnitOfWork(kernel.engine),
    )
    before = kernel.status()

    first = worker.run_once(limit=1, as_of=NOW)
    resumed = worker_type(
        unit_of_work_factory=lambda: OntologyUnitOfWork(kernel.engine),
    ).run_once(limit=10, as_of=NOW)
    after = kernel.status()

    assert [event.sequence for event in first] == [1]
    assert [event.sequence for event in resumed] == [2]
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.outbox.consumer_cursor(consumer_name) == 2
    assert after.action_counts == before.action_counts
    assert after.outbox_event_count == before.outbox_event_count
    assert after.outbox_latest_sequence == before.outbox_latest_sequence


def test_projection_consumers_keep_separate_cursors(tmp_path: Path) -> None:
    outbox_worker = getattr(operator_workers, "ProductOutboxWorker", None)
    invalidator = getattr(operator_workers, "OperatorReadModelInvalidator", None)
    assert outbox_worker is not None
    assert invalidator is not None
    kernel = _kernel_with_events(tmp_path, count=1)

    def factory():
        return OntologyUnitOfWork(kernel.engine)

    outbox_worker(unit_of_work_factory=factory).run_once(limit=1, as_of=NOW)

    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.outbox.consumer_cursor("product_sse_delivery") == 1
        assert uow.outbox.consumer_cursor("operator_read_model_invalidation") == 0
    assert [
        event.sequence
        for event in invalidator(unit_of_work_factory=factory).run_once(
            limit=1,
            as_of=NOW,
        )
    ] == [1]


def test_projection_consumer_applies_each_event_before_advancing_cursor(
    tmp_path: Path,
) -> None:
    kernel = _kernel_with_events(tmp_path)
    projected: list[int] = []

    def project(event) -> None:
        projected.append(event.sequence)
        if event.sequence == 2:
            raise RuntimeError("projection unavailable")

    worker = operator_workers.OperatorReadModelInvalidator(
        unit_of_work_factory=lambda: OntologyUnitOfWork(kernel.engine),
        project_event=project,
    )

    with pytest.raises(RuntimeError, match="projection unavailable"):
        worker.run_once(limit=10, as_of=NOW)

    assert projected == [1, 2]
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.outbox.consumer_cursor("operator_read_model_invalidation") == 1


def test_projection_signals_track_delivered_and_invalidated_sequences(
    tmp_path: Path,
) -> None:
    signals_type = getattr(operator_workers, "OperatorProjectionSignals", None)
    assert signals_type is not None
    signals = signals_type()
    kernel = _kernel_with_events(tmp_path, count=1)

    def factory():
        return OntologyUnitOfWork(kernel.engine)

    operator_workers.ProductOutboxWorker(
        unit_of_work_factory=factory,
        project_event=signals.deliver,
    ).run_once(limit=1, as_of=NOW)
    operator_workers.OperatorReadModelInvalidator(
        unit_of_work_factory=factory,
        project_event=signals.invalidate,
    ).run_once(limit=1, as_of=NOW)

    assert signals.delivered_sequence == 1
    assert signals.invalidated_sequence == 1
    assert signals.wait_for_delivery(after=0, timeout_seconds=0) is True
    assert signals.wait_for_delivery(after=1, timeout_seconds=0) is False


def test_real_application_lifespan_projects_committed_outbox(tmp_path: Path) -> None:
    data_dir = (tmp_path / "isolated").resolve()
    production_dir = (tmp_path / "production").resolve()
    settings = AppSettings(
        _env_file=None,
        data_dir=data_dir,
        production_data_dir=production_dir,
        operator_surface_mode="active",
        operator_runtime_scope="isolated_candidate",
        operator_token_signing_key="isolated-projection-signing-key-32-bytes",
    )
    kernel = build_ontology_kernel(settings)
    kernel.initialize()
    ingested = kernel.artifact_ingest.ingest(
        ArtifactIngestRequest(
            content=b"before-lifespan",
            content_type="text/plain",
            source_name="test",
            source_type="fixture",
            actor_id="source:test",
            actor_role=ActorRole.CONNECTOR,
            idempotency_key="projection-lifespan:ingest",
            retrieved_at=NOW,
        )
    )
    assert ingested.is_success
    runtime = OperatorRuntimeConfig(
        surface_mode=OperatorSurfaceMode.ACTIVE,
        runtime_scope=OperatorRuntimeScope.ISOLATED_CANDIDATE,
        data_dir=data_dir,
        production_data_dir=production_dir,
        running_commit="projection-lifespan-test",
    )
    services = build_product_services(settings, runtime_config=runtime)
    assert services.projection_signals is not None

    with TestClient(
        create_product_app(
            services,
            session_secret="projection-lifespan-session",
            csrf_secret="projection-lifespan-csrf",
            clock=lambda: NOW,
            runtime_config=runtime,
        )
    ):
        pass

    latest = services.kernel.status().outbox_latest_sequence
    assert services.projection_signals.delivered_sequence == latest
    assert services.projection_signals.invalidated_sequence == latest

    delivery_gate = operator_workers.OperatorProjectionSignals()
    services = replace(
        services,
        projection_signals=delivery_gate,
        infrastructure_workers=None,
    )
    without_workers = create_product_app(
        services,
        session_secret="projection-gate-session",
        csrf_secret="projection-gate-csrf",
        clock=lambda: NOW,
        runtime_config=runtime,
    )
    with TestClient(without_workers) as client:
        hidden = client.get("/api/v1/events/stream?after=0&once=true")
        assert "data:" not in hidden.text

        delivery_gate.deliver(SimpleNamespace(sequence=latest))
        visible = client.get("/api/v1/events/stream?after=0&once=true")
        assert "data:" in visible.text


def test_supervisor_runs_fixed_first_cycle_and_stops_consumers_in_reverse_order(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class RecordingWorker:
        def __init__(self, name: str) -> None:
            self.name = name

        def run_once(self, *, limit: int, as_of: datetime) -> tuple[object, ...]:
            assert limit == 7
            assert as_of == NOW
            events.append(f"run:{self.name}")
            return ()

        def stop_accepting(self) -> None:
            events.append(f"stop:{self.name}")

        async def close(self) -> None:
            events.append(f"close:{self.name}")

    names = (
        "evidence_freeze",
        "market_baseline",
        "candidate_generation",
        "confirmation_deadlines",
        "task_settlement",
        "review_materialization",
        "scoreboard_review_completion",
        "outbox",
        "read_model",
    )
    workers = {name: RecordingWorker(name) for name in names}
    supervisor = operator_workers.OperatorInfrastructureWorkers(
        data_dir=tmp_path,
        clock=lambda: NOW,
        poll_interval_seconds=60,
        batch_size=7,
        **workers,
    )

    async def run() -> None:
        await supervisor.start()
        supervisor.stop_accepting()
        await supervisor.drain_current_transactions()
        await supervisor.close()

    asyncio.run(run())

    assert events == [
        *(f"run:{name}" for name in names),
        *(f"stop:{name}" for name in reversed(names)),
        *(f"close:{name}" for name in reversed(names)),
    ]
