# Tasks: Bot LLM Fallback

**Input**: `.specify/specs/029-bot-llm-fallback/`
**Prerequisites**: `024-im-bot-adapter`, `026-telegram-bot-transport`, `027-telegram-bot-daemon`

## Phase 1: Spec and contract

- [x] T001 Create `029-bot-llm-fallback` spec + plan + tasks artifacts.
- [x] T002 Define fallback provider, adapter, and CLI configuration contract.

## Phase 2: TDD

- [x] T003 [P] [US2] Add failing OpenAI Responses fallback provider tests.
- [x] T004 [P] [US1] Add failing BotAdapter unsupported-message fallback test.
- [x] T005 [P] [US4] Add failing BotAdapter `/start` deterministic help test.
- [x] T006 [P] [US3] Add failing CLI `bot-dry-run` fallback wiring test.

## Phase 3: Implementation

- [x] T007 [US2] Implement OpenAI fallback provider and settings builder.
- [x] T008 [US1] Extend BotAdapter with optional fallback provider.
- [x] T009 [US4] Add deterministic `/start` and help response.
- [x] T010 [US3] Wire fallback into CLI bot and Telegram builders.

## Phase 4: Verification and continuity

- [x] T011 Run focused fallback verification.
- [x] T012 Update README/progress/memory/feature-list.
- [x] T013 Refresh graph assets after fallback addition.
