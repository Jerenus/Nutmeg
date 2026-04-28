# Implementation Plan: Telegram Bot Daemon

**Branch**: `027-telegram-bot-daemon` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/027-telegram-bot-daemon/spec.md`

## Summary

Add a `TelegramPollingDaemon` that aggregates repeated `TelegramBotRunner.poll_once()` calls. Add CLI `telegram-bot-run` for controlled daemon execution. Tests use fake runners/sleep functions only.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: stdlib time, existing Telegram runner  
**Storage**: no new storage  
**Testing**: unit tests and CLI monkeypatching  
**Constraints**: no network in tests, no token leakage, infinite mode supported but tests use max-polls, KeyboardInterrupt returns summary

## Design

- `TelegramDaemonSummary`: aggregate counts and stop reason.
- `TelegramPollingDaemon.run(offset, timeout, max_polls)`:
  - calls `runner.poll_once()` repeatedly
  - advances offset from summary.next_offset
  - sleeps between polls if more work remains
  - stops with `max_polls`, `interrupted`, or `error`
- CLI `telegram-bot-run --offset --timeout --poll-interval --max-polls --format`.
