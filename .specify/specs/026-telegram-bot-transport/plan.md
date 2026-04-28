# Implementation Plan: Telegram Bot Transport

**Branch**: `026-telegram-bot-transport` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/026-telegram-bot-transport/spec.md`

## Summary

Introduce a minimal Telegram transport around the existing no-network bot adapter. The production seam uses HTTPX against Telegram Bot API, while tests inject mock clients/runners.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing `httpx`, Typer CLI  
**Storage**: no new storage  
**Testing**: unit tests with fake HTTP client and CLI monkeypatching  
**Constraints**: no live network in tests, token never printed, owner allowlist by chat id, single-poll command only (no daemon loop yet)

## Design

- Settings: `telegram_bot_token`, `telegram_allowed_chat_ids`, `telegram_api_base_url`.
- `TelegramBotClient`: `get_updates(offset, timeout)` and `send_message(chat_id, text)`.
- `TelegramBotRunner`: filters update messages by chat id, routes allowed text to `BotAdapter`, sends response text, sends denial for unauthorized chat ids.
- CLI:
  - `telegram-bot-status --format text|json`
  - `telegram-bot-poll-once --offset N --timeout S --format text|json`
- Poll-once exits 2 if token missing, but status never fails merely because token is absent.
