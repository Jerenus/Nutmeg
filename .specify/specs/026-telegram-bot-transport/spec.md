# Feature Specification: Telegram Bot Transport

**Feature Branch**: `026-telegram-bot-transport`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Add the first real IM transport seam for Telegram while keeping tests no-network and owner-gated.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build Telegram API requests safely (Priority: P1)

As the operator, I want Telegram Bot API calls to be isolated behind a transport client that can be unit-tested without network calls.

**Independent Test**: Inject a mock HTTP client, call `send_message`, and verify the correct API path/body and parsed success response.

### User Story 2 - Route allowed Telegram messages to the bot adapter (Priority: P1)

As the private operator, I want Telegram updates from allowed chat ids to be routed to the existing `/brief` bot adapter and answered through Telegram.

**Independent Test**: Feed fake Telegram updates into a runner with a stub bot adapter and client; verify unauthorized chats are denied and authorized chats receive adapter output.

### User Story 3 - Provide CLI status and single-poll command (Priority: P1)

As the maintainer, I want a CLI command that can report Telegram bot configuration and optionally process one polling batch without leaking the token.

**Independent Test**: Run `telegram-bot-status` and `telegram-bot-poll-once` with env settings and mocked runner builder; verify JSON/text output, allowlist status, and no token leakage.
