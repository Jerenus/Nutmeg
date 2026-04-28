# Tasks: Provider Health Metrics

**Input**: `.specify/specs/014-provider-health-metrics/`
**Prerequisites**: `012-odds-event-cache-recovery`

## Phase 1: Spec and contract

- [x] T001 Create `014-provider-health-metrics` spec + plan + tasks artifacts.
- [x] T002 Define client-level provider health snapshot contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing tests for cache hit/miss and reconciliation counters.
- [x] T004 [P] [US2] Add failing tests for stale refresh and failure counters.
- [x] T005 [P] [US3] Add failing assertion that canonical odds snapshots remain unchanged.

## Phase 3: Implementation

- [x] T006 [US1] Implement health snapshot dataclass and counter updates.
- [x] T007 [US2] Record stale recovery success/failure and last error.
- [x] T008 [US3] Keep metrics separate from canonical odds snapshot payload.

## Phase 4: Verification and continuity

- [x] T009 Run focused provider/odds verification.
- [x] T010 Update docs, progress, and memory artifacts.
