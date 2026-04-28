# Tasks: Live Acceptance Scripts

**Input**: `.specify/specs/020-live-acceptance-scripts/`
**Prerequisites**: `015-historical-fixtures-ingestion`, `019-agent-status-cli`

## Phase 1: Spec and contract

- [x] T001 Create `020-live-acceptance-scripts` spec + plan + tasks artifacts.
- [x] T002 Define dry-run/live acceptance command contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing tests for default no-network dry-run command plan.
- [x] T004 [P] [US2] Add failing tests for live mode key gating.
- [x] T005 [P] [US3] Add failing tests/docs checks for Makefile/help discoverability.

## Phase 3: Implementation

- [x] T006 [US1] Implement `scripts/acceptance.sh` no-network mode.
- [x] T007 [US2] Implement explicit live mode with key checks.
- [x] T008 [US3] Add Makefile/docs references.

## Phase 4: Verification and continuity

- [x] T009 Run focused acceptance-script verification.
- [x] T010 Update docs, progress, and memory artifacts.
