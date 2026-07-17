from __future__ import annotations

from typing import Any

import httpx

from nutmeg.interfaces.bot.telegram import TelegramApiError
from nutmeg.notifications.models import (
    DeliveryTarget,
    NotificationRequest,
    ProviderResult,
    StoredArtifact,
)


class TelegramProvider:
    channel = "telegram"

    def __init__(self, client: Any) -> None:
        self._client = client

    def send(
        self,
        *,
        target: DeliveryTarget,
        request: NotificationRequest,
        artifacts: tuple[StoredArtifact, ...],
    ) -> ProviderResult:
        chat_id = _chat_id(target.destination)
        if chat_id is None:
            return ProviderResult.permanent_failure(
                "invalid_recipient", "Telegram recipient is not an integer"
            )
        if request.attachments:
            validation = _validate_document(request, artifacts)
            if validation is not None:
                return validation
            try:
                payload = self._client.send_document(
                    chat_id=chat_id,
                    document_path=artifacts[0].path,
                    caption=request.caption or request.subject,
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary classification
                return _classify_exception(exc)
        else:
            text = request.body or request.subject
            if len(text) > 4096:
                return ProviderResult.permanent_failure(
                    "text_too_long", "Telegram text exceeds 4096 characters"
                )
            try:
                payload = self._client.send_message(chat_id=chat_id, text=text)
            except Exception as exc:  # noqa: BLE001 - provider boundary classification
                return _classify_exception(exc)
        return ProviderResult.sent(_message_id(payload))

    def send_fallback(
        self,
        *,
        target: DeliveryTarget,
        request: NotificationRequest,
        error: ProviderResult,
    ) -> ProviderResult:
        chat_id = _chat_id(target.destination)
        if chat_id is None:
            return ProviderResult.permanent_failure(
                "invalid_recipient", "Telegram recipient is not an integer"
            )
        text = (
            f"{request.subject}: report attachment delivery failed "
            f"({error.error_code or 'unknown'})."
        )
        try:
            payload = self._client.send_message(chat_id=chat_id, text=text)
        except Exception as exc:  # noqa: BLE001 - provider boundary classification
            return _classify_exception(exc)
        return ProviderResult.sent(_message_id(payload))


def _validate_document(
    request: NotificationRequest, artifacts: tuple[StoredArtifact, ...]
) -> ProviderResult | None:
    if len(artifacts) != 1 or not artifacts[0].path.is_file():
        return ProviderResult.permanent_failure(
            "invalid_attachment", "Telegram document attachment is unavailable"
        )
    if artifacts[0].media_type != "application/pdf":
        return ProviderResult.permanent_failure(
            "invalid_attachment", "Telegram report attachment must be a PDF"
        )
    if len(request.caption or request.subject) > 1024:
        return ProviderResult.permanent_failure(
            "caption_too_long", "Telegram document caption exceeds 1024 characters"
        )
    return None


def _classify_exception(exc: Exception) -> ProviderResult:
    if isinstance(exc, TelegramApiError):
        code = exc.error_code or exc.status_code
        if code == 429:
            return ProviderResult.retryable_failure(
                "rate_limited",
                "Telegram rate limit reached",
                retry_after_seconds=exc.retry_after_seconds,
            )
        if exc.status_code is not None and exc.status_code >= 500:
            return ProviderResult.retryable_failure(
                "telegram_server_error", "Telegram service is temporarily unavailable"
            )
        return ProviderResult.permanent_failure(
            f"telegram_api_{code or 'error'}", "Telegram API rejected the request"
        )
    if isinstance(exc, httpx.TimeoutException):
        return ProviderResult.retryable_failure("timeout", "Telegram request timed out")
    if isinstance(exc, httpx.RequestError):
        return ProviderResult.retryable_failure(
            "network_error", "Telegram network request failed"
        )
    if isinstance(exc, OSError):
        return ProviderResult.permanent_failure(
            "invalid_attachment", "Telegram attachment could not be read"
        )
    return ProviderResult.permanent_failure(
        "telegram_client_error", "Telegram client rejected the request"
    )


def _message_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("message_id") is None:
        return None
    return str(result["message_id"])


def _chat_id(destination: str) -> int | None:
    try:
        return int(destination)
    except (TypeError, ValueError):
        return None
