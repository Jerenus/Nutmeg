from pathlib import Path

import httpx

from nutmeg.interfaces.bot.telegram import TelegramApiError
from nutmeg.notifications.models import (
    DeliveryTarget,
    NotificationAttachment,
    NotificationRequest,
    StoredArtifact,
)
from nutmeg.notifications.telegram import TelegramProvider


class FakeTelegramClient:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or {"ok": True, "result": {"message_id": 91}}
        self.error = error
        self.documents = []
        self.messages = []

    def send_document(self, *, chat_id, document_path, caption):
        self.documents.append((chat_id, Path(document_path), caption))
        if self.error is not None:
            raise self.error
        return self.result

    def send_message(self, *, chat_id, text):
        self.messages.append((chat_id, text))
        if self.error is not None:
            raise self.error
        return self.result


def _request(tmp_path: Path) -> tuple[NotificationRequest, StoredArtifact]:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF")
    request = NotificationRequest(
        kind="decision.close.report",
        business_key="2026-07-17",
        stage="close",
        semantic_fingerprint="report",
        subject="Decision report",
        caption="Decision report",
        attachments=(NotificationAttachment(report, "application/pdf"),),
    )
    artifact = StoredArtifact(
        artifact_id="A-1",
        notification_id="N-1",
        path=report,
        original_name="report.pdf",
        media_type="application/pdf",
        size_bytes=4,
        sha256="0" * 64,
    )
    return request, artifact


def test_telegram_provider_returns_message_id(tmp_path: Path) -> None:
    request, artifact = _request(tmp_path)
    client = FakeTelegramClient()
    provider = TelegramProvider(client)

    result = provider.send(
        target=DeliveryTarget("telegram", "owner", "123"),
        request=request,
        artifacts=(artifact,),
    )

    assert result.status.value == "sent"
    assert result.provider_message_id == "91"
    assert client.documents[0][0] == 123


def test_telegram_provider_honors_rate_limit(tmp_path: Path) -> None:
    request, artifact = _request(tmp_path)
    provider = TelegramProvider(
        FakeTelegramClient(
            error=TelegramApiError(
                "Too Many Requests",
                status_code=429,
                error_code=429,
                retry_after_seconds=3,
            )
        )
    )

    result = provider.send(
        target=DeliveryTarget("telegram", "owner", "123"),
        request=request,
        artifacts=(artifact,),
    )

    assert result.status.value == "retryable_failed"
    assert result.error_code == "rate_limited"
    assert result.retry_after_seconds == 3


def test_telegram_provider_classifies_connection_error(tmp_path: Path) -> None:
    request, artifact = _request(tmp_path)
    error = httpx.ConnectError("offline", request=httpx.Request("POST", "https://example.test"))
    provider = TelegramProvider(FakeTelegramClient(error=error))

    result = provider.send(
        target=DeliveryTarget("telegram", "owner", "123"),
        request=request,
        artifacts=(artifact,),
    )

    assert result.status.value == "retryable_failed"
    assert result.error_code == "network_error"
    assert "example.test" not in (result.error_message or "")


def test_telegram_provider_rejects_missing_artifact_before_network(tmp_path: Path) -> None:
    request, _artifact = _request(tmp_path)
    client = FakeTelegramClient()

    result = TelegramProvider(client).send(
        target=DeliveryTarget("telegram", "owner", "123"),
        request=request,
        artifacts=(),
    )

    assert result.status.value == "permanent_failed"
    assert result.error_code == "invalid_attachment"
    assert client.documents == []
