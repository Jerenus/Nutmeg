# Tasks: Today Briefs

**Input**: `.specify/specs/025-today-briefs/`
**Prerequisites**: `023-operator-match-brief`, `024-im-bot-adapter`

## Phase 1: Spec and contract

- [x] T001 Create `025-today-briefs` spec + plan + tasks artifacts.
- [x] T002 Define today fixture/brief JSON contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing CLI test for demo fixture list text output.
- [x] T004 [P] [US2] Add failing CLI test for `--briefs` JSON output with stub workflow.
- [x] T005 [P] [US3] Add failing CLI test for empty local cache JSON output.

## Phase 3: Implementation

- [x] T006 [US1] Implement today fixture candidate payload builder.
- [x] T007 [US2] Implement `today-briefs --briefs` workflow fan-out.
- [x] T008 [US3] Implement JSON/text rendering and empty-state handling.

## Phase 4: Verification and continuity

- [x] T009 Run focused today briefs verification.
- [x] T010 Update README/progress/memory/feature-list.
- [x] T011 Refresh graph assets after CLI change.
