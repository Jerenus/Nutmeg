# Tasks: IM Bot Adapter

**Input**: `.specify/specs/024-im-bot-adapter/`
**Prerequisites**: `023-operator-match-brief`

## Phase 1: Spec and contract

- [x] T001 Create `024-im-bot-adapter` spec + plan + tasks artifacts.
- [x] T002 Define bot command/response contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing parser tests for `/brief` and unsupported messages.
- [x] T004 [P] [US2] Add failing adapter test for successful brief response.
- [x] T005 [P] [US3] Add failing CLI dry-run tests for text/json/failure.

## Phase 3: Implementation

- [x] T006 [US1] Implement bot command parser and errors.
- [x] T007 [US2] Implement bot adapter response renderer over existing workflow.
- [x] T008 [US3] Implement `bot-dry-run` CLI command.

## Phase 4: Verification and continuity

- [x] T009 Run focused bot adapter verification.
- [x] T010 Update README/progress/memory/feature-list.
- [x] T011 Refresh graph assets after new bot module.
