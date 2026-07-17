from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine

from nutmeg.notifications.models import DeliveryTarget, NotificationRequest
from nutmeg.notifications.repository import SqlAlchemyNotificationRepository
from nutmeg.storage.bootstrap import create_state_schema


def _repository(tmp_path) -> SqlAlchemyNotificationRepository:
    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}", future=True)
    create_state_schema(engine)
    return SqlAlchemyNotificationRepository(engine)


def _failure_request(fingerprint: str = "failure-a") -> NotificationRequest:
    return NotificationRequest.text(
        kind="operations.failure",
        business_key="decision-close:2026-07-17",
        stage="close",
        semantic_fingerprint=fingerprint,
        subject="decision-close failed",
        text="capture-closing failed",
    )


def test_repository_creates_revision_and_records_attempt(tmp_path) -> None:
    repo = _repository(tmp_path)
    notification = repo.create_notification(
        _failure_request(),
        targets=(DeliveryTarget("telegram", "owner", "7627818415", True),),
        artifacts=(),
    )
    delivery = repo.list_deliveries(notification.notification_id)[0]
    attempt = repo.start_attempt(delivery.delivery_id, started_at=datetime.now(UTC))

    repo.finish_attempt(
        attempt.attempt_id,
        delivered_at=datetime.now(UTC),
        provider_message_id="42",
    )

    bundle = repo.get_bundle(notification.notification_id)
    assert bundle.notification.revision == 1
    assert bundle.deliveries[0].status.value == "sent"
    assert bundle.attempts[0].provider_message_id == "42"


def test_repository_assigns_revision_within_business_stage(tmp_path) -> None:
    repo = _repository(tmp_path)
    first = repo.create_notification(
        _failure_request("failure-a"),
        targets=(DeliveryTarget("telegram", "owner", "1", True),),
        artifacts=(),
    )
    second = repo.create_notification(
        _failure_request("failure-b"),
        targets=(DeliveryTarget("telegram", "owner", "1", True),),
        artifacts=(),
    )

    assert first.revision == 1
    assert second.revision == 2
    assert repo.get_by_dedupe_key(_failure_request("failure-a").dedupe_key) == first


def test_repository_marks_stale_sending_uncertain(tmp_path) -> None:
    repo = _repository(tmp_path)
    notification = repo.create_notification(
        _failure_request(),
        targets=(DeliveryTarget("telegram", "owner", "1", True),),
        artifacts=(),
    )
    delivery = repo.list_deliveries(notification.notification_id)[0]
    repo.start_attempt(
        delivery.delivery_id,
        started_at=datetime.now(UTC) - timedelta(minutes=10),
    )

    changed = repo.mark_stale_sending_uncertain(
        stale_before=datetime.now(UTC) - timedelta(minutes=5)
    )

    assert changed == 1
    bundle = repo.get_bundle(notification.notification_id)
    assert bundle.notification.status.value == "uncertain"
    assert bundle.deliveries[0].status.value == "uncertain"
