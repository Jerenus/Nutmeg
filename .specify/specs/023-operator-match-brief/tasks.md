# Tasks: Operator Match Brief

**Input**: `.specify/specs/023-operator-match-brief/`
**Prerequisites**: `016-agent-execution-path`, `017-agent-llm-synthesis`, `020-live-acceptance-scripts`

## Phase 1: Spec and contract

- [x] T001 Create `023-operator-match-brief` spec + plan + tasks artifacts.
- [x] T002 Define JSON/text brief contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing JSON CLI test for successful brief payload.
- [x] T004 [P] [US2] Add failing text CLI test for successful brief rendering.
- [x] T005 [P] [US3] Add failing CLI test for truthful workflow failure.

## Phase 3: Implementation

- [x] T006 [US1] Implement match brief payload assembler.
- [x] T007 [US2] Implement `match-brief` CLI text rendering.
- [x] T008 [US3] Preserve non-zero failure behavior and JSON error payload.

## Phase 4: Verification and continuity

- [x] T009 Run focused match brief verification.
- [x] T010 Update README/progress/memory/feature-list.
- [x] T011 Refresh graph assets after CLI change.
