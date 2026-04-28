# Tasks: Analysis Judgment v0

**Input**: `.specify/specs/008-analysis-judgment-v0/`
**Prerequisites**: existing snapshot and odds flows available

## Phase 1: Setup and foundations

- [x] T001 Create `008-analysis-judgment-v0` spec + plan + tasks artifacts.
- [x] T002 Define analysis domain models and wire a dedicated analysis service entry point.

## Phase 2: TDD for service and CLI

- [x] T003 [P] [US1] Add failing service tests for four-part judgment assembly and insufficient-evidence handling.
- [x] T004 [P] [US2] Add failing service tests proving snapshot and odds evidence are surfaced separately and truthfully.
- [x] T005 [P] [US3] Add failing CLI tests for `analyze-match` text/JSON output and clean failure paths.

## Phase 3: Implementation

- [x] T006 [US1] Implement the analysis domain models and synthesis logic.
- [x] T007 [US2] Integrate snapshot and odds services into the analysis workflow without duplicating provider logic.
- [x] T008 [US3] Implement the CLI command and rendering for text/JSON output.

## Phase 4: Verification and continuity

- [x] T009 Run local tests and verification, then update continuity artifacts.
- [x] T010 Update architecture docs and feature tracking for the first agent-facing analysis slice.
