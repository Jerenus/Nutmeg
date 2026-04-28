# Tasks: Event Data Tactical Models v0

**Input**: Design documents from `.specify/specs/038-event-data-tactical-models-v0/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli-contract.md`, `quickstart.md`

**Tests**: Required. Nutmeg constitution requires Superpowers/TDD; user-visible behavior starts with failing tests before implementation.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently after the foundation is complete.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and does not depend on incomplete tasks
- **[Story]**: Maps to the user story in `spec.md` as `[US1]`, `[US2]`, or `[US3]`
- Every task names exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add package scaffolding and deterministic sample path without feature behavior.

- [x] T001 Create event-data sample package marker in `nutmeg/event_data/__init__.py`
- [x] T002 [P] Create deterministic local event sample in `nutmeg/event_data/samples/epl-001-events.json`
- [x] T003 [P] Create architecture documentation stub in `docs/architecture/event-data-tactical-models.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish event-data domain and service seams that all stories depend on.

**CRITICAL**: No user story work begins until this phase is complete.

- [x] T004 [P] Write failing domain tests for normalized events, event quality, pass network, spatial value, contribution, artifact, and report serialization in `tests/test_event_data.py`
- [x] T005 Implement event-data domain dataclasses and enums in `nutmeg/domain/event_data.py`
- [x] T006 [P] Write failing service-factory test for local provider defaults and bundled sample discovery in `tests/test_event_data.py`
- [x] T007 Implement local provider constructor and sample path discovery in `nutmeg/services/event_data.py`

**Checkpoint**: Domain entities and local provider seam exist and fail safely.

---

## Phase 3: User Story 1 - Load normalized event data for a fixture (Priority: P1) MVP

**Goal**: A user can load local fixture event data and see normalized events plus truthful quality status.

**Independent Test**: Provide a deterministic local JSON file and verify normalized event fields, quality status, missing-file behavior, and metadata preservation.

### Tests for User Story 1

- [x] T008 [P] [US1] Write failing provider test for StatsBomb-like pass, shot, carry, and defensive-action normalization in `tests/test_event_data.py`
- [x] T009 [P] [US1] Write failing provider test for missing, empty, and malformed event files producing unavailable quality without fabricated events in `tests/test_event_data.py`
- [x] T010 [P] [US1] Write failing provider test for unknown provider fields being retained in event metadata in `tests/test_event_data.py`

### Implementation for User Story 1

- [x] T011 [US1] Implement StatsBomb-like and simplified JSON event parsing in `nutmeg/services/event_data.py`
- [x] T012 [US1] Implement missing/empty/malformed data quality handling in `nutmeg/services/event_data.py`
- [x] T013 [US1] Implement coordinate clamping, outcome normalization, and provider metadata preservation in `nutmeg/services/event_data.py`

**Checkpoint**: User Story 1 is independently usable for local event ingestion.

---

## Phase 4: User Story 2 - Build event-data tactical models (Priority: P1)

**Goal**: A user can build a pass network, xT-lite spatial-value summary, VAEP-lite player contribution summary, and deterministic SVG artifacts from normalized events.

**Independent Test**: Seed events, build a report, and verify model labels, network nodes/edges, spatial value actions, player contribution ranks, warnings, artifacts, and unavailable sections.

### Tests for User Story 2

- [x] T014 [P] [US2] Write failing service test for completed-pass network nodes and edges from actual event locations in `tests/test_event_data.py`
- [x] T015 [P] [US2] Write failing service test for xT-lite progressive pass/carry values and player aggregation in `tests/test_event_data.py`
- [x] T016 [P] [US2] Write failing service test for VAEP-lite contribution summary with explicit heuristic warnings in `tests/test_event_data.py`
- [x] T017 [P] [US2] Write failing service test for unavailable model sections when event data is sparse in `tests/test_event_data.py`
- [x] T018 [P] [US2] Write failing service test for deterministic SVG artifact generation and optional file writes in `tests/test_event_data.py`

### Implementation for User Story 2

- [x] T019 [US2] Implement pass-network aggregation in `nutmeg/services/event_data.py`
- [x] T020 [US2] Implement xT-lite grid values and progressive action deltas in `nutmeg/services/event_data.py`
- [x] T021 [US2] Implement VAEP-lite player contribution aggregation in `nutmeg/services/event_data.py`
- [x] T022 [US2] Implement unavailable-section and warning policy in `nutmeg/services/event_data.py`
- [x] T023 [US2] Implement deterministic SVG artifact renderers and output-dir writes in `nutmeg/services/event_data.py`
- [x] T024 [US2] Document model labels, limitations, and artifact semantics in `docs/architecture/event-data-tactical-models.md`

**Checkpoint**: User Story 2 is independently usable for event-data tactical modeling.

---

## Phase 5: User Story 3 - Expose event tactical reports from CLI and artifacts (Priority: P2)

**Goal**: A user can run a CLI command for JSON/text event tactical reports and optional SVG files.

**Independent Test**: Run the CLI with a local sample or fake service and verify parseable JSON/text output, model labels, quality status, artifact paths, and unavailable reports.

### Tests for User Story 3

- [x] T025 [P] [US3] Write failing CLI registration test for `event-tactical-models` help in `tests/test_cli.py`
- [x] T026 [P] [US3] Write failing CLI JSON contract test for model labels, quality, report sections, warnings, and artifact paths in `tests/test_cli.py`
- [x] T027 [P] [US3] Write failing CLI test for unavailable event data returning parseable JSON without failure in `tests/test_cli.py`

### Implementation for User Story 3

- [x] T028 [US3] Implement `build_event_tactical_model_service()` in `nutmeg/interfaces/cli.py`
- [x] T029 [US3] Implement `event-tactical-models` text/JSON CLI command in `nutmeg/interfaces/cli.py`
- [x] T030 [US3] Add README usage examples for `event-tactical-models` in `README.md`
- [x] T031 [US3] Add `event-data-tactical-models-v0` entry to `feature-list.json`

**Checkpoint**: User Story 3 is independently usable from CLI and ready for future bot/client reuse.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Finish docs, verification, graph assets, and feature status.

- [x] T032 [P] Add completion notes to `.specify/specs/038-event-data-tactical-models-v0/verification.md`
- [x] T033 [P] Update `docs/architecture/design-gap-audit.md` to mark event-data tactical models v0 as started/closed for v0 scope
- [x] T034 Run focused event-data tests and record evidence in `.specify/specs/038-event-data-tactical-models-v0/verification.md`
- [x] T035 Run `uv run ruff check .`, `python3 -m compileall nutmeg`, and `bash scripts/verify.sh`, then record evidence in `.specify/specs/038-event-data-tactical-models-v0/verification.md`
- [x] T036 Refresh graph assets with `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` and review `graphify-out/GRAPH_REPORT.md`
- [x] T037 Update `memory/2026-04-26.md` and `agent-progress.md` with implementation rationale and verification evidence
- [x] T038 Mark `.specify/specs/038-event-data-tactical-models-v0/spec.md` status according to final verification result

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1; blocks all user stories.
- **Phase 3 US1**: Depends on Phase 2; MVP event ingestion.
- **Phase 4 US2**: Depends on US1 normalized events.
- **Phase 5 US3**: Depends on US2 reports.
- **Phase 6 Polish**: Depends on all implemented stories.

### User Story Dependencies

- **US1**: Independent MVP after foundation.
- **US2**: Requires US1 event normalization.
- **US3**: Requires US2 report service.

### Within Each User Story

- Write failing tests first.
- Implement only enough behavior to make the failing tests pass.
- Keep model labels explicit and conservative.
- Verify story independently before moving to the next story.
- Do not introduce network calls, heavy plotting dependencies, or full VAEP/xT parity claims.

## Parallel Opportunities

- T002 and T003 can run in parallel after T001.
- T004 and T006 can run in parallel because both are test-only tasks.
- US1 test tasks T008 through T010 can be written together before implementation.
- US2 test tasks T014 through T018 can be written together before implementation.
- US3 test tasks T025 through T027 can be written together before implementation.
- Polish doc/verification tasks T032 and T033 can run in parallel.

## Implementation Strategy

1. Complete setup and foundation.
2. Deliver US1 event ingestion as the MVP.
3. Deliver US2 models and artifacts.
4. Deliver US3 CLI parity.
5. Complete docs, feature registry, graph, and full verification.
