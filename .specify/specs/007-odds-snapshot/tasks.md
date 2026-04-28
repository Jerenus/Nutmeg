# Tasks: Odds Snapshot and Fair Probability

**Input**: `.specify/specs/007-odds-snapshot/`
**Prerequisites**: spec.md, plan.md, research.md, data-model.md, contracts/cli-odds-snapshot.md

## Phase 1: Setup and foundations

- [x] T001 Create the `007-odds-snapshot` Spec Kit artifacts and update `.specify/feature.json` to point at the active odds feature directory.
- [x] T002 Define the odds domain boundary in `nutmeg/domain/odds.py` and wire the new service entry point in `nutmeg/services/odds.py` and `nutmeg/interfaces/cli.py`.

## Phase 2: TDD for provider normalization and fair math

- [x] T003 [P] [US1] Add failing API adapter tests in `tests/test_api_football.py` for pre-match odds normalization, canonical supported markets, and duplicate bookmaker-row handling.
- [x] T004 [P] [US2] Add failing fair-probability and aggregation tests in `tests/test_betting.py` and `tests/test_odds_service.py` for no-vig derivation, best price, average price, and incomplete-market behavior.
- [x] T005 [P] [US3] Add failing CLI tests in `tests/test_cli.py` for `odds-snapshot` text/JSON output, unknown fixture failure, and missing-provider behavior.

## Phase 3: Implementation

- [x] T006 [US1] Implement the API-Football odds adapter in `nutmeg/data/api_football.py` and the odds domain models in `nutmeg/domain/odds.py`.
- [x] T007 [US2] Implement the odds snapshot assembly and fair-probability aggregation in `nutmeg/services/odds.py` and extend reusable betting helpers in `nutmeg/models/betting.py`.
- [x] T008 [US3] Implement the `odds-snapshot` CLI flow in `nutmeg/interfaces/cli.py` and document the architecture in `docs/architecture/odds-snapshot.md`.

## Phase 4: Acceptance and review

- [x] T009 Run local verification plus at least one live odds acceptance pass from `.specify/specs/007-odds-snapshot/quickstart.md`, then update `memory/2026-04-24.md` and `agent-progress.md`.
- [x] T010 Perform a spec-aligned odds review, record residual provider-expansion gaps in `docs/architecture/odds-snapshot.md`, and sync the feature status in `.specify/specs/007-odds-snapshot/spec.md`.
- [x] T011 Extend the odds contract and tests to cover persisted historical market summaries (`movement`, `movement_span`, `drift_vs_current`) plus provider-selection behavior.
- [x] T012 Sync `contracts/cli-odds-snapshot.md`, verification, and review artifacts so the active spec reflects the current history-aware odds path.
