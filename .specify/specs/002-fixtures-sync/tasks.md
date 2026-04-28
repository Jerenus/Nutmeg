# Tasks: Fixtures Sync Sprint 0 Slice

**Input**: `.specify/specs/002-fixtures-sync/`
**Prerequisites**: spec.md, plan.md

## Phase 1: Harness and spec alignment

- [x] T001 Create continuity artifacts: `init.sh`, `agent-progress.md`, `feature-list.json`.
- [x] T002 Create `002-fixtures-sync` spec + plan + tasks docs.
- [x] T003 Update docs to reflect the v0.3 shared-facts/user-state boundary.

## Phase 2: Storage and provider infrastructure

- [x] T004 Add league catalog metadata and season resolution helpers.
- [x] T005 Implement API-Football client with pagination, error parsing, and fixture normalization.
- [x] T006 Implement DuckDB shared fixture repository and SQLite sync-run repository.

## Phase 3: CLI and observability

- [x] T007 Implement `fixtures-sync` service and CLI command.
- [x] T008 Add LangSmith tracing helper for CLI/sync operations.
- [x] T009 Update `doctor` to report harness and latest sync metadata.

## Phase 4: Verification

- [x] T010 Add tests for API client parsing and error handling.
- [x] T011 Add tests for DuckDB fixture storage and SQLite sync metadata.
- [x] T012 Add CLI tests for sync/list/doctor behavior.
- [x] T013 Add CI workflow and pass local verification.
- [x] T014 Update continuity artifacts with final status.
