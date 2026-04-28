# Tasks: Pre-Match Snapshot Completion Sprint 1 Slice

**Input**: `.specify/specs/004-pre-match-snapshot/`
**Prerequisites**: spec.md, plan.md

## Phase 1: Feature and schema foundation

- [x] T001 Create `004-pre-match-snapshot` spec + plan + tasks docs.
- [x] T002 Extend fixture domain/storage so provider team ids survive sync and local reads.
- [x] T003 Expand snapshot domain models for market value, injuries, and lineups.

## Phase 2: TDD provider behavior

- [x] T004 Add failing tests for API-Football fixture normalization and fixture repository round-trip with team ids.
- [x] T005 Add failing tests for Transfermarkt market-value normalization.
- [x] T006 Add failing tests for injury normalization and confirmed lineup normalization.
- [x] T007 Add failing tests for probable-lineup fallback and source/status attribution.
- [x] T008 Add failing CLI tests for expanded snapshot JSON/text output.

## Phase 3: Implementation

- [x] T009 Implement Transfermarkt market-value adapter and lineup-history helper.
- [x] T010 Extend API-Football adapter with injuries and lineups endpoints.
- [x] T011 Implement expanded snapshot assembly with confirmed/probable lineup logic.
- [x] T012 Update CLI rendering and docs for the fuller Sprint 1 snapshot.

## Phase 4: Acceptance and review

- [x] T013 Update continuity artifacts and feature tracking for the fuller Sprint 1 slice.
- [x] T014 Run lint, tests, verify script, and a manual end-to-end snapshot acceptance pass.
- [x] T015 Perform a Sprint 1 spec-aligned review and capture residual gaps before moving to the next sprint.
