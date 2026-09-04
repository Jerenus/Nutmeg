from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository import schema_workflow as sw
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.services.telegram_ticket_confirmation import (
    TelegramOwnerHeartbeatService,
)

AT = datetime(2026, 9, 5, 2, tzinfo=UTC)


def _service(tmp_path: Path, *, owner: str = "openclaw-primary"):
    engine = build_ontology_engine(tmp_path / f"{owner}.db")
    run_migrations(engine)
    action_service = ActionService(lambda: OntologyUnitOfWork(engine))
    service = TelegramOwnerHeartbeatService(
        action_service=action_service,
        account_id="nutmeg",
        owner_instance_id=owner,
        transport_label="openclaw-telegram",
        owner_mode="openclaw",
        router_version="ntc-v1",
        lease_duration=timedelta(seconds=90),
    )
    return engine, service


def _high_water(engine) -> tuple[int, int]:
    with engine.connect() as connection:
        actions = connection.scalar(select(func.count()).select_from(schema.actions))
        outbox = connection.scalar(select(func.count()).select_from(sw.outbox_events))
    return int(actions or 0), int(outbox or 0)


def test_first_pulse_registers_once_and_renewals_do_not_advance_business_high_water(
    tmp_path: Path,
) -> None:
    engine, service = _service(tmp_path)

    first = service.pulse(observed_at=AT)
    registered_high_water = _high_water(engine)
    second = service.pulse(observed_at=AT + timedelta(seconds=30))
    third = service.pulse(observed_at=AT + timedelta(seconds=60))

    assert first.heartbeat_sequence == 1
    assert second.heartbeat_sequence == 2
    assert third.heartbeat_sequence == 3
    assert _high_water(engine) == registered_high_water
    assert registered_high_water == (1, 1)
    with OntologyUnitOfWork(engine) as uow:
        action = uow.connection.execute(
            select(schema.actions.c.action_type, schema.actions.c.actor_role)
        ).one()
        row = uow.operator_result.telegram_owner_heartbeat(
            account_id="nutmeg",
            owner_instance_id="openclaw-primary",
        )
    assert action == ("register_telegram_update_owner", "deterministic_system")
    assert row is not None
    assert row.heartbeat_sequence == 3
    assert row.observed_at == (AT + timedelta(seconds=60)).isoformat()
    assert row.lease_expires_at == (AT + timedelta(seconds=150)).isoformat()


def test_owner_status_uses_only_formal_lease_and_reports_stable_blocking_codes(
    tmp_path: Path,
) -> None:
    _engine, service = _service(tmp_path)

    missing = service.status(as_of=AT)
    service.pulse(observed_at=AT)
    available = service.status(as_of=AT + timedelta(seconds=30))
    expired = service.status(as_of=AT + timedelta(seconds=91))
    future = service.status(as_of=AT - timedelta(seconds=3))

    assert (missing.available, missing.blocking_code) == (
        False,
        "telegram_owner_missing",
    )
    assert (available.available, available.blocking_code) == (True, None)
    assert (expired.available, expired.blocking_code) == (
        False,
        "telegram_owner_heartbeat_expired",
    )
    assert (future.available, future.blocking_code) == (
        False,
        "telegram_owner_clock_skew",
    )


def test_two_fresh_registered_owners_block_confirmation(tmp_path: Path) -> None:
    engine = build_ontology_engine(tmp_path / "owners.db")
    run_migrations(engine)
    action_service = ActionService(lambda: OntologyUnitOfWork(engine))
    primary = TelegramOwnerHeartbeatService(
        action_service=action_service,
        account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        transport_label="openclaw-telegram",
        owner_mode="openclaw",
        router_version="ntc-v1",
        lease_duration=timedelta(seconds=90),
    )
    duplicate = TelegramOwnerHeartbeatService(
        action_service=action_service,
        account_id="nutmeg",
        owner_instance_id="native-secondary",
        transport_label="native-telegram",
        owner_mode="native_distinct_token",
        router_version="native-v1",
        lease_duration=timedelta(seconds=90),
    )

    primary.pulse(observed_at=AT)
    duplicate.pulse(observed_at=AT)

    status = primary.status(as_of=AT + timedelta(seconds=1))
    assert status.available is False
    assert status.blocking_code == "telegram_update_owner_conflict"
