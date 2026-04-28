# Tasks: Richer Pre-Match Snapshot Expansion

**Input**: `.specify/specs/006-prematch-snapshot-expansion/`
**Prerequisites**: spec.md, plan.md, feature 005 complete

## Phase 1: Snapshot model expansion

- [x] T001 Create `006-prematch-snapshot-expansion` spec + plan + tasks docs.
- [x] T002 Expand snapshot domain models for environment, availability, and matchup/trend sections.
- [x] T003 Extend fixture/provider metadata normalization for referee and richer fixture context.

## Phase 2: TDD for new sections

- [x] T004 Add failing tests for environment/schedule context and weather reuse.
- [x] T005 Add failing tests for suspensions, returning players, expected absences summary, and bench depth.
- [x] T006 Add failing tests for head-to-head, home/away splits, goals/xG trend, and set-piece trend.
- [x] T007 Add failing CLI tests for richer text and JSON snapshot rendering.

## Phase 3: Implementation

- [x] T008 Implement environment/schedule context assembly.
- [x] T009 Implement deeper availability assembly.
- [x] T010 Implement matchup/trend aggregation.
- [x] T011 Update CLI rendering and architecture docs for the richer snapshot.

## Phase 4: Acceptance and review

- [x] T012 Update continuity artifacts and feature tracking for the richer snapshot slice.
- [x] T013 Run lint, tests, verify script, and a manual richer snapshot acceptance pass.
- [x] T014 Perform a spec-aligned review and capture residual Sprint 1 gaps before any odds work.
