from __future__ import annotations

import time
from collections.abc import Callable

from nutmeg.config.settings import AppSettings, get_settings
from nutmeg.interfaces.bot.telegram import TelegramBotClient
from nutmeg.notifications.artifacts import ArtifactStore
from nutmeg.notifications.models import DeliveryTarget
from nutmeg.notifications.repository import SqlAlchemyNotificationRepository
from nutmeg.notifications.service import NotificationService
from nutmeg.notifications.telegram import TelegramProvider
from nutmeg.storage.bootstrap import build_state_engine, create_state_schema, ensure_storage_paths


def build_notification_service(
    *,
    settings: AppSettings | None = None,
    telegram_client=None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> NotificationService:
    resolved_settings = settings or get_settings()
    ensure_storage_paths(resolved_settings)
    engine = build_state_engine(resolved_settings)
    create_state_schema(engine)

    client = telegram_client
    if client is None and resolved_settings.telegram_bot_token:
        client = TelegramBotClient(
            token=resolved_settings.telegram_bot_token,
            base_url=resolved_settings.telegram_api_base_url,
        )
    providers = {"telegram": TelegramProvider(client)} if client is not None else {}
    targets = tuple(
        DeliveryTarget(
            channel="telegram",
            recipient_key="owner",
            destination=str(chat_id),
            required=True,
        )
        for chat_id in parse_telegram_chat_ids(resolved_settings.telegram_allowed_chat_ids)
    )
    return NotificationService(
        repository=SqlAlchemyNotificationRepository(engine),
        artifact_store=ArtifactStore(resolved_settings.data_dir / "notifications" / "artifacts"),
        providers=providers,
        targets=targets,
        sleep_fn=sleep_fn,
    )


def parse_telegram_chat_ids(raw_value: str | None) -> tuple[int, ...]:
    if not raw_value:
        return ()
    return tuple(
        sorted({int(chunk.strip()) for chunk in raw_value.split(",") if chunk.strip()})
    )
