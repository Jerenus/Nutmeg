# Tasks: Telegram Bot Daemon

**Input**: `.specify/specs/027-telegram-bot-daemon/`
**Prerequisites**: `026-telegram-bot-transport`

## Phase 1: Spec and contract

- [x] T001 Create `027-telegram-bot-daemon` spec + plan + tasks artifacts.
- [x] T002 Define daemon summary and CLI contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing daemon max-polls aggregate test.
- [x] T004 [P] [US2] Add failing daemon KeyboardInterrupt summary test.
- [x] T005 [P] [US3] Add failing CLI `telegram-bot-run` JSON test.

## Phase 3: Implementation

- [x] T006 [US1] Implement `TelegramPollingDaemon` and aggregate summary.
- [x] T007 [US2] Handle KeyboardInterrupt without traceback.
- [x] T008 [US3] Implement `telegram-bot-run` CLI.

## Phase 4: Verification and continuity

- [x] T009 Run focused Telegram daemon verification.
- [x] T010 Update README/progress/memory/feature-list.
- [x] T011 Refresh graph assets after daemon addition.
