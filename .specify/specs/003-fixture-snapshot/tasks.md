# Tasks: Fixture Snapshot Sprint 1 Slice

**Input**: `.specify/specs/003-fixture-snapshot/`
**Prerequisites**: spec.md, plan.md

## Phase 1: Spec and mapping foundation

- [x] T001 Create `003-fixture-snapshot` spec + plan + tasks docs.
- [x] T002 Extend league/team config to carry soccerdata source mappings and snapshot scope notes.
- [x] T003 Add repository support for loading one cached fixture by `fixture_id`.

## Phase 2: TDD the enrichment path

- [x] T004 Add failing tests for team mapping resolution and unsupported league behavior.
- [x] T005 Add failing tests for soccerdata normalization into season metrics, recent form, and shot summary.
- [x] T006 Add failing tests for snapshot service assembly and deferred-section reporting.
- [x] T007 Add failing CLI tests for `fixture-snapshot` success and failure paths.

## Phase 3: Implement the minimal slice

- [x] T008 Add `soccerdata` dependency and implement the `nutmeg.data.soccerdata_client` adapter.
- [x] T009 Implement snapshot domain models plus `FixtureSnapshotService`.
- [x] T010 Wire `fixture-snapshot` into the CLI with text and JSON output.
- [x] T011 Document the slice in architecture docs and repository README.

## Phase 4: Verify and review

- [x] T012 Update continuity artifacts (`agent-progress.md`, `feature-list.json`, memory log) with Sprint 1 slice status.
- [x] T013 Run lint, tests, verify script, and targeted manual snapshot checks.
- [x] T014 Perform a spec-aligned review of the final diff and capture any residual gaps.
