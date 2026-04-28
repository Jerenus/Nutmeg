# Tasks: Historical Fixtures Ingestion

**Input**: `.specify/specs/015-historical-fixtures-ingestion/`
**Prerequisites**: `002-fixtures-sync`, `006-prematch-snapshot-expansion`

## Phase 1: Spec and contract

- [x] T001 Create `015-historical-fixtures-ingestion` spec + plan + tasks artifacts.
- [x] T002 Extend fixture repository contract with prior finished fixture lookup.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing sync/CLI tests for `past_days` date range.
- [x] T004 [P] [US2] Add failing repository tests for most recent finished prior fixture lookup.
- [x] T005 [P] [US3] Add failing snapshot tests for computed home/away rest days.

## Phase 3: Implementation

- [x] T006 [US1] Implement fixture sync `past_days` and CLI `--past-days` option.
- [x] T007 [US2] Implement DuckDB prior finished fixture lookup.
- [x] T008 [US3] Compute rest days in `FixtureSnapshotService` environment context.

## Phase 4: Verification and continuity

- [x] T009 Run focused sync/repository/snapshot/CLI verification.
- [x] T010 Update architecture, progress, and memory artifacts.
