# Tasks: Market Intelligence Signals

**Input**: `.specify/specs/013-market-intelligence-signals/`
**Prerequisites**: `010-market-shape-expansion`, `011-asian-handicap-expansion`, odds history support

## Phase 1: Spec and contract

- [x] T001 Create `013-market-intelligence-signals` spec + plan + tasks artifacts.
- [x] T002 Define deterministic movement/disagreement thresholds within analysis service.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing analysis test for match-winner movement evidence.
- [x] T004 [P] [US2] Add failing analysis test for bookmaker disagreement caveat and confidence cap.
- [x] T005 [P] [US3] Add failing CLI JSON/text tests proving evidence stays in existing fields.

## Phase 3: Implementation

- [x] T006 [US1] Consume odds history in analysis odds summary.
- [x] T007 [US2] Detect bookmaker disagreement and use it in caveats/confidence.
- [x] T008 [US3] Preserve CLI output contract with no top-level schema changes.

## Phase 4: Verification and continuity

- [x] T009 Run focused analysis/CLI verification.
- [x] T010 Update architecture, progress, and memory artifacts.
