# Tasks: Telegram Offset Persistence

**Input**: `.specify/specs/030-telegram-offset-persistence/`
**Prerequisites**: `027-telegram-bot-daemon`, `029-bot-llm-fallback`

## Phase 1: Spec and contract

- [x] T001 Create `030-telegram-offset-persistence` spec + plan + tasks artifacts.
- [x] T002 Define file offset store and CLI persistence contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing offset store and daemon persistence tests.
- [x] T004 [P] [US2] Add failing CLI stored-offset default test.
- [x] T005 [P] [US3] Add failing CLI explicit-offset override test.

## Phase 3: Implementation

- [x] T006 [US1] Implement `TelegramOffsetStore` and daemon write-after-poll.
- [x] T007 [US2] Wire default offset file into `telegram-bot-run`.
- [x] T008 [US3] Preserve explicit `--offset` override and JSON metadata.

## Phase 4: Verification and continuity

- [x] T009 Run focused offset persistence verification.
- [x] T010 Update README/progress/memory/feature-list.
- [x] T011 Refresh graph assets after offset persistence addition.
