"""Outbound Telegram client (sending only; the inbound bot runner was retired 2026-10-03)."""
from nutmeg.interfaces.bot.telegram import TelegramApiError, TelegramBotClient

__all__ = ["TelegramApiError", "TelegramBotClient"]
