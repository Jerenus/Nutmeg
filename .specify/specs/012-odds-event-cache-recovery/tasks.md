# Tasks: Odds Event Cache Recovery

**Input**: `.specify/specs/012-odds-event-cache-recovery/`
**Prerequisites**: `007-odds-snapshot`, The Odds API reconciliation path

## Phase 1: Spec and contract

- [x] T001 Create `012-odds-event-cache-recovery` spec + plan + tasks artifacts.
- [x] T002 Extend odds event repository contract with explicit invalidation.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing provider test for stale cached event id recovery.
- [x] T004 [P] [US2] Add failing provider test for truthful recovery failure.
- [x] T005 [P] [US3] Add failing repository test for fixture/provider cache invalidation isolation.

## Phase 3: Implementation

- [x] T006 [US3] Implement repository invalidation for in-memory tests and DuckDB storage.
- [x] T007 [US1] Implement The Odds API stale-event retry and replacement-cache upsert.
- [x] T008 [US2] Preserve non-stale error behavior and improve stale recovery error context.

## Phase 4: Verification and continuity

- [x] T009 Run focused The Odds API / repository / odds service verification.
- [x] T010 Update architecture, progress, and memory artifacts.
