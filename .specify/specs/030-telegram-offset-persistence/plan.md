# Implementation Plan: Telegram Offset Persistence

**Branch**: `030-telegram-offset-persistence` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/030-telegram-offset-persistence/spec.md`

## Summary

Add a small file-backed Telegram offset store and wire it into `telegram-bot-run` by default. Manual `--offset` remains available and wins over stored state.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: stdlib pathlib, existing Telegram daemon  
**Storage**: local text file under `settings.data_dir / state / telegram-bot.offset`  
**Testing**: unit tests with temp offset files and CLI monkeypatching  
**Constraints**: no network in tests, no token leakage, invalid offset file should not crash daemon startup

## Design

- `TelegramOffsetStore`: `read()` returns `int | None`; `write(offset)` creates parent dirs and stores integer text.
- `TelegramPollingDaemon`: optional `offset_store`; writes `summary.next_offset` after each poll.
- `telegram-bot-run`: default offset file enabled; `--offset` overrides stored value; `--offset-file` can point elsewhere; `--no-offset-file` disables persistence.
- JSON/text summaries include offset persistence metadata.
