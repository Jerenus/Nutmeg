# Superpowers Task Coverage Review: Event Data Tactical Models v0

Date: 2026-04-26  
Feature directory: `.specify/specs/038-event-data-tactical-models-v0`

## Loaded Artifacts

- `spec.md`
- `plan.md`
- `tasks.md`
- `data-model.md`
- `contracts/cli-contract.md`
- `research.md`
- `quickstart.md`

## Extracted Requirements

- **R01 [TESTABLE]**: Local StatsBomb-like event files normalize fixture id, team, player, type, minute, location, end location, outcome, and source event id.
- **R02 [TESTABLE]**: Missing or empty event files report unavailable and do not synthesize events.
- **R03 [TESTABLE]**: Unsupported provider fields are retained as metadata without breaking reports.
- **R04 [TESTABLE]**: Completed pass events produce pass-network nodes and edges from event locations.
- **R05 [TESTABLE]**: Successful progressive passes/carries produce xT-lite zone and player deltas.
- **R06 [TESTABLE]**: Shots/progressive/defensive actions produce VAEP-lite player contributions with heuristic labels.
- **R07 [TESTABLE]**: CLI JSON output includes fixture id, quality, event count, pass network, xT-lite, VAEP-lite, artifacts, warnings, and responsible model labels.
- **R08 [TESTABLE]**: Output directories write deterministic SVG files and return paths in JSON.
- **R09 [TESTABLE]**: Unavailable event data returns successful JSON with unavailable sections and no fabricated charts.
- **R10 [TESTABLE]**: Normalized event entities preserve provider, time, coordinates, outcomes, xG, and metadata.
- **R11 [STRUCTURAL]**: v0 remains no-network and does not change existing tactical proxy flows.
- **R12 [OBSERVABLE]**: Documentation explains xT-lite/VAEP-lite limitations and future full-model path.
- **R13 [TESTABLE]**: Seeded local event file normalizes at least 10 events in local tests.
- **R14 [TESTABLE]**: Existing full verification continues to pass.

## Coverage Matrix

| Req | Coverage Tasks | Status |
|-----|----------------|--------|
| R01 | T008, T011, T013 | Covered |
| R02 | T009, T012 | Covered |
| R03 | T010, T013 | Covered |
| R04 | T014, T019 | Covered |
| R05 | T015, T020 | Covered |
| R06 | T016, T021 | Covered |
| R07 | T026, T028, T029 | Covered |
| R08 | T018, T023, T026 | Covered |
| R09 | T017, T022, T027 | Covered |
| R10 | T004, T005, T008, T011, T013 | Covered |
| R11 | T007, T012, T024, T035 | Covered |
| R12 | T024, T030, T033 | Covered |
| R13 | T008, T034 | Covered |
| R14 | T035, T036 | Covered |

## Coverage Gaps

No coverage gaps detected.

## Task Quality and TDD Readiness

- **Format**: PASS. 38/38 tasks use strict checkbox format with sequential IDs and exact paths.
- **User-story organization**: PASS. Tasks are grouped by US1 through US3 with independent tests and checkpoints.
- **Test-first coverage**: PASS. Each user story starts with failing test tasks before implementation tasks.
- **File specificity**: PASS. Every task names concrete target files.
- **Broad-task risk**: LOW. Model-building tasks are separated into pass-network, xT-lite, VAEP-lite, unavailable-section, and SVG slices.
- **Superpowers readiness**: READY. `speckit.superb.tdd` can enforce RED/GREEN per story.

## Coverage Review Summary

**Requirements extracted**: 14  
**Fully covered**: 14 (100%)  
**Partially covered**: 0  
**Gaps identified**: 0  
**Task quality issues**: 0 blocking issues  
**TDD readiness**: READY

**Decision**: Coverage complete. `tasks.md` is ready for the mandatory TDD gate before implementation.
