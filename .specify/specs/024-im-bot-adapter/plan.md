# Implementation Plan: IM Bot Adapter

**Branch**: `024-im-bot-adapter` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/024-im-bot-adapter/spec.md`

## Summary

Add a transport-agnostic bot adapter in `nutmeg.interfaces.bot` that parses IM messages and delegates `/brief` to the existing `MatchAnalysisAgentWorkflow`. Add `nutmeg bot-dry-run` so the adapter is testable and useful without network credentials.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: stdlib dataclasses, existing Typer CLI  
**Storage**: no new storage  
**Testing**: unit tests for adapter + CLI tests with stubbed workflow  
**Constraints**: no Telegram/Discord SDK dependency yet, no network calls, preserve match-brief failure semantics, avoid duplicating analysis logic

## Design

- `BotCommand`: parsed command name, fixture id, query, raw text.
- `BotResponse`: status, text, payload, error.
- `parse_bot_message(text)`: supports `/brief <fixture_id> <query>` and `brief <fixture_id> <query>`.
- `BotAdapter.handle_message(text)`: parse -> workflow.run -> reuse `build_match_brief_payload`-compatible payload assembler callback -> compact text rendering.
- CLI `bot-dry-run --message ... --format text|json` constructs the adapter from `build_agent_workflow()` and exits 2 on failed responses.
