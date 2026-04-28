# Tasks: Telegram Bot Transport

**Input**: `.specify/specs/026-telegram-bot-transport/`
**Prerequisites**: `024-im-bot-adapter`

## Phase 1: Spec and contract

- [x] T001 Create `026-telegram-bot-transport` spec + plan + tasks artifacts.
- [x] T002 Define Telegram settings/client/runner/CLI contracts.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing Telegram client request tests.
- [x] T004 [P] [US2] Add failing runner authorization/routing tests.
- [x] T005 [P] [US3] Add failing CLI status and poll-once tests.

## Phase 3: Implementation

- [x] T006 [US1] Implement Telegram API client.
- [x] T007 [US2] Implement Telegram runner over existing BotAdapter.
- [x] T008 [US3] Implement Telegram settings and CLI commands.

## Phase 4: Verification and continuity

- [x] T009 Run focused Telegram bot verification.
- [x] T010 Update README/progress/memory/feature-list.
- [x] T011 Refresh graph assets after transport module.
