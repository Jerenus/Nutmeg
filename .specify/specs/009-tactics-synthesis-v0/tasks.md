# Tasks: Tactics Synthesis v0

**Input**: `.specify/specs/009-tactics-synthesis-v0/`
**Prerequisites**: `008-analysis-judgment-v0` implemented

## Phase 1: Spec and contract

- [x] T001 Create `009-tactics-synthesis-v0` spec + plan + tasks artifacts.
- [x] T002 Extend the analysis domain contract for tactical evidence and conflict state.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing service tests for tactical evidence extraction and sparse-tactical fallbacks.
- [x] T004 [P] [US2] Add failing service tests for contradictory evidence and confidence downgrades.
- [x] T005 [P] [US3] Add failing CLI tests proving the richer JSON/text contract remains stable.

## Phase 3: Implementation

- [x] T006 [US1] Implement tactical evidence extraction from the existing snapshot context.
- [x] T007 [US2] Implement synthesis conflict detection and confidence adjustment.
- [x] T008 [US3] Update CLI rendering to expose richer evidence sections without breaking the house judgment format.

## Phase 4: Verification and continuity

- [x] T009 Run focused verification for analysis/tactics paths.
- [x] T010 Update architecture and continuity artifacts for the deeper analysis slice.
