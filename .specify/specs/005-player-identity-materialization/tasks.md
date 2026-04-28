# Tasks: Player Identity Alignment and Provider Materialization

**Input**: `.specify/specs/005-player-identity-materialization/`
**Prerequisites**: spec.md, plan.md

## Phase 1: Schema and domain foundation

- [x] T001 Create `005-player-identity-materialization` spec + plan + tasks docs.
- [x] T002 Extend DuckDB bootstrap with player identity, alias, venue reference, weather cache, and materialized provider tables.
- [x] T003 Expand snapshot domain entities for canonical player identity and environment cache inputs.

## Phase 2: TDD for identity and cache behavior

- [x] T004 Add failing repository tests for player identity alias resolution and unresolved matches.
- [x] T005 Add failing materialization tests for local Transfermarkt and soccerdata cache reads.
- [x] T006 Add failing weather/venue cache tests for reuse behavior.
- [x] T007 Add failing snapshot tests proving injuries exclude probable lineup players by canonical identity, not only raw names.
- [x] T008 Add failing CLI tests for a reference/materialization refresh command.

## Phase 3: Implementation

- [x] T009 Implement reference repository and player alias catalog loading.
- [x] T010 Implement Transfermarkt local materialization and local-first read path.
- [x] T011 Implement soccerdata materialization and local-first read path.
- [x] T012 Implement Open-Meteo venue/weather cache adapter.
- [x] T013 Implement snapshot integration with canonical player identity exclusion.
- [x] T014 Implement CLI refresh command and architecture docs for the new shared reference layer.

## Phase 4: Acceptance and review

- [x] T015 Update continuity artifacts and feature tracking for the new infrastructure slice.
- [x] T016 Run lint, tests, verify script, and a manual cache-backed snapshot acceptance pass.
- [x] T017 Perform a spec-aligned review and capture residual risks before starting richer snapshot expansion.
