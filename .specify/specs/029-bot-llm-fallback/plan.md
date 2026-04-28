# Implementation Plan: Bot LLM Fallback

**Branch**: `029-bot-llm-fallback` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/029-bot-llm-fallback/spec.md`

## Summary

Add an optional OpenAI Responses API fallback provider for the bot layer. Keep `/brief` deterministic analysis as the primary route, but let unsupported messages and failed brief attempts return a GPT-5.5 fallback when configured.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing `httpx`, Typer, BotAdapter  
**Storage**: no new storage  
**Testing**: provider tests with `httpx.MockTransport`, adapter tests with fake provider, CLI monkeypatch tests  
**Constraints**: default-off, no secret leakage, no OpenAI network calls in tests, no new SDK dependency

## Design

- Extend `AppSettings` with OpenAI fallback fields.
- Add `OpenAiBotFallbackProvider` and `build_bot_fallback_provider(settings)` in `nutmeg.agents.llm_provider`.
- Extend `BotAdapter` with optional `fallback_provider` and deterministic `/start` help.
- Wire fallback provider into `bot-dry-run` and Telegram runner construction.
- Update doctor/status surfaces with configured booleans only, not secrets.
