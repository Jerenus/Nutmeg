# Tasks: Provider Health Persistence

**Input**: `.specify/specs/022-provider-health-persistence/`
**Prerequisites**: `014-provider-health-metrics`, `019-agent-status-cli`, `021-graph-refresh`

## Phase 1: Spec and contract

- [x] T001 Create `022-provider-health-persistence` spec + plan + tasks artifacts.
- [x] T002 Define persisted health table/repository/status contract.

## Phase 2: TDD

- [x] T003 [P] [US1] Add failing repository round-trip test for persisted health snapshots.
- [x] T004 [P] [US1] Add failing The Odds API client test for persisted cumulative health across instances.
- [x] T005 [P] [US2] Add failing CLI status test for no-network persisted health reporting.

## Phase 3: Implementation

- [x] T006 [US1] Add analytics schema and DuckDB health repository.
- [x] T007 [US1] Wire optional health repository into The Odds API client.
- [x] T008 [US2] Surface persisted health in `agent-status` JSON/text payload.
- [x] T009 [US3] Preserve default/API-Football behavior and snapshot non-intrusion.

## Phase 4: Verification and continuity

- [x] T010 Run focused provider health persistence verification.
- [x] T011 Refresh graph assets after new repository dependency path.
- [x] T012 Update progress and memory artifacts.
