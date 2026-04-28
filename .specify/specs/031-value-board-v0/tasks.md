# Tasks: Value Board v0

**Input**: `.specify/specs/031-value-board-v0/`
**Prerequisites**: `007-odds-snapshot`, `008-analysis-judgment-v0`, `015-historical-fixtures-ingestion`

## Phase 1: Spec and contract

- [x] T001 Create `031-value-board-v0` spec + plan + tasks artifacts.
- [x] T002 Define value-board domain contract in `nutmeg/domain/value.py`.
- [x] T003 Document the design gap and update active Spec Kit plan reference.

## Phase 2: TDD

- [x] T004 [P] [US1] Add failing pricing model tests in `tests/test_dixon_coles.py`.
- [x] T005 [P] [US2] Add failing service tests in `tests/test_value_service.py`.
- [x] T006 [P] [US3] Add failing CLI JSON contract tests in `tests/test_cli.py`.

## Phase 3: Implementation

- [x] T007 [US1] Implement deterministic baseline pricing in `nutmeg/models/dixon_coles.py`.
- [x] T008 [US2] Implement value-board assembly and ranking in `nutmeg/services/value.py`.
- [x] T009 [US3] Implement `value-board` CLI wiring and text/JSON rendering in `nutmeg/interfaces/cli.py`.

## Phase 4: Documentation and verification

- [x] T010 Update docs, README, `feature-list.json`, `agent-progress.md`, and memory.
- [x] T011 Run focused tests, ruff, compileall, full `scripts/verify.sh`, and refresh graph assets.
- [x] T012 Review spec coverage and mark this spec verified when evidence is recorded.
