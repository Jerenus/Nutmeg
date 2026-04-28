# Tasks: Asian Handicap Expansion

**Input**: `.specify/specs/011-asian-handicap-expansion/`
**Prerequisites**: `010-market-shape-expansion` implemented

## Phase 1: Spec and contract

- [x] T001 Create `011-asian-handicap-expansion` spec + plan + tasks artifacts.
- [x] T002 Extend canonical odds coverage and analysis evidence for richer handicap pressure.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing odds tests for broader handicap normalization.
- [x] T004 [P] [US2] Add failing analysis tests for handicap-pressure reasoning.
- [x] T005 [P] [US3] Add failing CLI tests proving the richer handicap coverage stays contract-safe.

## Phase 3: Implementation

- [x] T006 [US1] Implement broader handicap normalization across supported providers.
- [x] T007 [US2] Integrate handicap-pressure signals into deterministic analysis output.
- [x] T008 [US3] Update CLI output as needed while preserving the canonical contract.

## Phase 4: Verification and continuity

- [x] T009 Run focused odds/analysis verification.
- [x] T010 Update architecture and continuity artifacts.
