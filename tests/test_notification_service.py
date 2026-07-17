from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from nutmeg.config.settings import AppSettings
from nutmeg.notifications.artifacts import ArtifactStore
from nutmeg.notifications.models import (
    DeliveryTarget,
    NotificationAttachment,
    NotificationRequest,
    ProviderResult,
)
from nutmeg.notifications.repository import SqlAlchemyNotificationRepository
from nutmeg.notifications.service import NotificationService
from nutmeg.notifications.wiring import build_notification_service
from nutmeg.storage.bootstrap import create_state_schema


class ScriptedProvider:
    channel = "telegram"

    def __init__(self, results: list[ProviderResult]) -> None:
        self.results = list(results)
        self.calls: list[str] = []
        self.fallback_calls: list[str] = []
        self.fallback_requests = []

    def send(self, *, target, request, artifacts) -> ProviderResult:
        self.calls.append(target.destination)
        return self.results.pop(0)

    def send_fallback(self, *, target, request, error) -> ProviderResult:
        self.fallback_calls.append(target.destination)
        self.fallback_requests.append(request)
        return ProviderResult.sent("fallback-1")


@pytest.fixture
def repository() -> SqlAlchemyNotificationRepository:
    engine = create_engine("sqlite:///:memory:", future=True)
    create_state_schema(engine)
    return SqlAlchemyNotificationRepository(engine)


def _request(fingerprint: str) -> NotificationRequest:
    return NotificationRequest.text(
        kind="operations.failure",
        business_key="am:2026-07-17",
        stage="am",
        semantic_fingerprint=fingerprint,
        subject="AM failed",
        text="fetch failed",
    )


def _service(repository, tmp_path: Path, provider, targets) -> NotificationService:
    return NotificationService(
        repository=repository,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        providers={"telegram": provider},
        targets=targets,
        sleep_fn=lambda _seconds: None,
    )


def test_service_deduplicates_success(repository, tmp_path: Path) -> None:
    provider = ScriptedProvider([ProviderResult.sent("message-1")])
    service = _service(
        repository,
        tmp_path,
        provider,
        (DeliveryTarget("telegram", "owner", "1", True),),
    )

    first = service.publish(_request("same"))
    second = service.publish(_request("same"))

    assert first.status.value == "sent"
    assert second.status.value == "deduplicated"
    assert provider.calls == ["1"]


def test_service_isolates_partial_failure(repository, tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            ProviderResult.sent("message-1"),
            ProviderResult.permanent_failure("invalid_chat", "chat not found"),
        ]
    )
    service = _service(
        repository,
        tmp_path,
        provider,
        (
            DeliveryTarget("telegram", "owner-a", "1", True),
            DeliveryTarget("telegram", "owner-b", "2", True),
        ),
    )

    outcome = service.publish(_request("partial"))

    assert outcome.status.value == "partial"
    assert [item.status.value for item in outcome.deliveries] == [
        "sent",
        "permanent_failed",
    ]


def test_service_retries_transient_only(repository, tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            ProviderResult.retryable_failure(
                "timeout", "timed out", retry_after_seconds=0
            ),
            ProviderResult.sent("message-2"),
        ]
    )
    service = _service(
        repository,
        tmp_path,
        provider,
        (DeliveryTarget("telegram", "owner", "1", True),),
    )

    outcome = service.publish(_request("retry"))

    assert outcome.status.value == "sent"
    assert provider.calls == ["1", "1"]
    assert len(repository.get_bundle(outcome.notification_id).attempts) == 2


def test_service_dry_run_has_no_persistent_side_effects(repository, tmp_path: Path) -> None:
    provider = ScriptedProvider([])
    service = _service(
        repository,
        tmp_path,
        provider,
        (DeliveryTarget("telegram", "owner", "1", True),),
    )

    outcome = service.publish(_request("dry"), dry_run=True)

    assert outcome.status.value == "dry_run"
    assert provider.calls == []
    assert repository.get_by_dedupe_key(_request("dry").dedupe_key) is None
    assert not (tmp_path / "artifacts").exists()


def test_service_missing_targets_is_a_recorded_configuration_failure(
    repository, tmp_path: Path
) -> None:
    provider = ScriptedProvider([])
    service = _service(repository, tmp_path, provider, ())

    outcome = service.publish(_request("missing-target"))

    assert outcome.status.value == "failed"
    assert outcome.deliveries[0].error_code == "missing_recipient"


def test_wiring_sorts_configured_telegram_recipients(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=tmp_path / "data",
        telegram_bot_token="secret",
        telegram_allowed_chat_ids="22, 11",
    )
    service = build_notification_service(
        settings=settings,
        telegram_client=object(),
        sleep_fn=lambda _seconds: None,
    )

    outcome = service.publish(_request("wired"), dry_run=True)

    assert [item.destination for item in outcome.deliveries] == ["11", "22"]


def test_retry_does_not_resend_successful_recipient(repository, tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            ProviderResult.sent("message-1"),
            ProviderResult.permanent_failure("invalid_chat", "chat not found"),
            ProviderResult.sent("message-2"),
        ]
    )
    service = _service(
        repository,
        tmp_path,
        provider,
        (
            DeliveryTarget("telegram", "owner-a", "1", True),
            DeliveryTarget("telegram", "owner-b", "2", True),
        ),
    )
    first = service.publish(_request("manual-retry"))

    second = service.retry(first.notification_id, include_permanent=True)

    assert second.status.value == "sent"
    assert provider.calls == ["1", "2", "2"]


def test_stale_sending_recovery_is_marked_possible_duplicate(
    repository, tmp_path: Path
) -> None:
    current = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    provider = ScriptedProvider([ProviderResult.sent("message-2")])
    request = _request("uncertain")
    notification = repository.create_notification(
        request,
        targets=(DeliveryTarget("telegram", "owner", "1", True),),
        artifacts=(),
        created_at=current - timedelta(minutes=10),
    )
    delivery = repository.list_deliveries(notification.notification_id)[0]
    repository.start_attempt(
        delivery.delivery_id,
        started_at=current - timedelta(minutes=10),
    )
    service = NotificationService(
        repository=repository,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        providers={"telegram": provider},
        targets=(DeliveryTarget("telegram", "owner", "1", True),),
        sleep_fn=lambda _seconds: None,
        now_fn=lambda: current,
    )

    outcome = service.publish(request)

    assert outcome.status.value == "sent"
    assert outcome.possible_duplicate is True
    assert repository.get_bundle(notification.notification_id).attempts[-1].possible_duplicate


def test_attachment_fallback_network_call_is_recorded(repository, tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF")
    provider = ScriptedProvider(
        [ProviderResult.permanent_failure("invalid_attachment", "bad document")]
    )
    service = _service(
        repository,
        tmp_path,
        provider,
        (DeliveryTarget("telegram", "owner", "1", True),),
    )
    request = NotificationRequest(
        kind="decision.close.report",
        business_key="2026-07-17",
        stage="close",
        semantic_fingerprint="fallback",
        subject="Decision report",
        attachments=(NotificationAttachment(source, "application/pdf"),),
    )

    outcome = service.publish(request)

    attempts = repository.get_bundle(outcome.notification_id).attempts
    assert outcome.status.value == "failed"
    assert provider.fallback_calls == ["1"]
    assert provider.fallback_requests[0].metadata["notification_id"] == outcome.notification_id
    assert [item.outcome.value for item in attempts] == ["failed", "fallback_sent"]
    assert attempts[-1].provider_message_id == "fallback-1"


def test_explicit_retry_binds_recipient_after_configuration_is_fixed(
    repository, tmp_path: Path
) -> None:
    missing_service = _service(repository, tmp_path, ScriptedProvider([]), ())
    failed = missing_service.publish(_request("fixed-config"))
    provider = ScriptedProvider([ProviderResult.sent("message-1")])
    fixed_service = _service(
        repository,
        tmp_path,
        provider,
        (DeliveryTarget("telegram", "owner", "99", True),),
    )

    recovered = fixed_service.retry(failed.notification_id, include_permanent=True)

    assert recovered.status.value == "sent"
    assert recovered.deliveries[0].destination == "99"
    assert provider.calls == ["99"]
