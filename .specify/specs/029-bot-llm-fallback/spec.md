# Feature Specification: Bot LLM Fallback

**Feature Branch**: `029-bot-llm-fallback`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Add a GPT-5.5-backed fallback so the Telegram/Nutmeg bot responds usefully to `/start`, help, unsupported natural-language messages, and deterministic brief failures.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Natural-language fallback response (Priority: P1)

As the private operator, I want the bot to answer normal Chinese or English messages instead of only accepting `/brief` commands.

**Independent Test**: Inject a fake fallback provider into `BotAdapter`, send `今天有哪些热门比赛？`, and verify the adapter returns a successful fallback response without calling the match workflow.

### User Story 2 - Safe OpenAI Responses provider (Priority: P1)

As the maintainer, I want the fallback provider isolated behind an HTTP adapter using OpenAI's Responses API and never leaking the API key in output.

**Independent Test**: Use an `httpx.MockTransport`, call the provider, and verify it posts to `/responses` with `model=gpt-5.5`, extracts response text, and keeps the key only in the Authorization header.

### User Story 3 - CLI/Telegram wiring (Priority: P1)

As the operator, I want `bot-dry-run` and Telegram runner construction to use the same optional fallback configuration.

**Independent Test**: Monkeypatch the fallback builder in CLI, run `bot-dry-run --message "hello" --format json`, and verify the fallback payload is returned and no secret appears.

### User Story 4 - Deterministic help for `/start` (Priority: P2)

As a new bot user, I want `/start` or `help` to immediately explain usable commands even if no OpenAI key is configured.

**Independent Test**: Send `/start` through `BotAdapter` without fallback configured and verify a successful help response listing `/brief`, `popular-matches`, and daemon polling expectations.

## Functional Requirements

- **FR-001**: Fallback MUST be default-off and require both `NUTMEG_BOT_LLM_FALLBACK_ENABLED=true` and an OpenAI API key.
- **FR-002**: The default fallback model MUST be configurable and default to `gpt-5.5`.
- **FR-003**: The provider MUST use HTTPX directly against the OpenAI Responses API endpoint `/responses` to avoid adding a new SDK dependency.
- **FR-004**: Bot output MUST never include OpenAI API keys or Telegram bot tokens.
- **FR-005**: `/brief` success MUST keep the deterministic Nutmeg match-brief path as primary behavior.
- **FR-006**: Unsupported messages and failed deterministic `/brief` attempts SHOULD use the fallback provider when configured; otherwise they must return a deterministic help/error message.
