# Tasks: News Information Provider v0

**Input**: Design documents from `.specify/specs/039-news-information-provider-v0/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli-contract.md`, `quickstart.md`

**Tests**: Required. Nutmeg constitution requires Superpowers/TDD; user-visible behavior starts with failing tests before implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and does not depend on incomplete tasks
- **[Story]**: Maps to the user story in `spec.md` as `[US1]`, `[US2]`, or `[US3]`
- Every task names exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add local information package scaffolding and docs stub without feature behavior.

- [x] T001 Create information sample package marker in `nutmeg/information/__init__.py`
- [x] T002 [P] Create deterministic local information sample in `nutmeg/information/samples/epl-001-information.json`
- [x] T003 [P] Create architecture documentation stub in `docs/architecture/information-provider.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish information domain and service seams that all stories depend on.

- [x] T004 [P] Write failing domain tests for information item, source health, digest serialization, reliability labels, and unavailable state in `tests/test_information_service.py`
- [x] T005 Implement information domain dataclasses and enums in `nutmeg/domain/information.py`
- [x] T006 [P] Write failing service-factory test for local source defaults and bundled sample discovery in `tests/test_information_service.py`
- [x] T007 Implement local information provider constructor and sample path discovery in `nutmeg/services/information.py`

**Checkpoint**: Domain entities and local information provider seam exist and fail safely.

---

## Phase 3: User Story 1 - Normalize local match information (Priority: P1) MVP

**Goal**: A user can load local JSON/RSS information and receive normalized, deduplicated, source-attributed fixture items.

**Independent Test**: Provide deterministic local files and verify normalization, deduplication, reliability labels, missing-source behavior, and metadata preservation.

### Tests for User Story 1

- [x] T008 [P] [US1] Write failing service test for local JSON item normalization, fixture/team filtering, and reliability labels in `tests/test_information_service.py`
- [x] T009 [P] [US1] Write failing service test for duplicate URL/title-source collapse keeping newest item in `tests/test_information_service.py`
- [x] T010 [P] [US1] Write failing service test for missing, empty, and malformed source files returning unavailable digest without fabricated items in `tests/test_information_service.py`
- [x] T011 [P] [US1] Write failing service test for local RSS/Atom-style parsing with publication timestamps and links in `tests/test_information_service.py`

### Implementation for User Story 1

- [x] T012 [US1] Implement local JSON information parsing and fixture/team filtering in `nutmeg/services/information.py`
- [x] T013 [US1] Implement deduplication, latest timestamp, summary, and reliability warning policy in `nutmeg/services/information.py`
- [x] T014 [US1] Implement missing/empty/malformed source handling in `nutmeg/services/information.py`
- [x] T015 [US1] Implement local RSS/Atom parsing in `nutmeg/services/information.py`

**Checkpoint**: User Story 1 is independently usable for local information digests.

---

## Phase 4: User Story 2 - Add information digest to match analysis surfaces (Priority: P1)

**Goal**: A user can see real source-attributed information in match workspace and client surfaces.

**Independent Test**: Build a client match workspace with local information provider and verify summary, item list, reliability labels, warnings, and unavailable fallback.

### Tests for User Story 2

- [x] T016 [P] [US2] Write failing service test for `ClientService.match_workspace()` consuming real information digest payload in `tests/test_client_service.py`
- [x] T017 [P] [US2] Write failing service test proving rumor/unverified information does not raise actionability by itself in `tests/test_client_service.py`
- [x] T018 [P] [US2] Write failing CLI/client builder test proving `build_client_service()` wires `FixtureInformationService` in `tests/test_cli.py`

### Implementation for User Story 2

- [x] T019 [US2] Implement client-compatible `build_information()` payload in `nutmeg/services/information.py`
- [x] T020 [US2] Update `ClientService.match_workspace()` to pass fixture team context to information providers when supported in `nutmeg/services/client.py`
- [x] T021 [US2] Wire `FixtureInformationService` into `build_client_service()` in `nutmeg/interfaces/cli.py`
- [x] T022 [US2] Update match workspace template rendering for information item lists and reliability labels in `nutmeg/interfaces/web/templates/client/match.html`
- [x] T023 [US2] Document client information panel behavior in `docs/architecture/ai-native-client.md`

**Checkpoint**: User Story 2 is independently usable in match workspace/client flows.

---

## Phase 5: User Story 3 - Expose fixture information from CLI (Priority: P2)

**Goal**: A user can run a CLI command for text/JSON fixture information digests.

**Independent Test**: Run the CLI with local sample/fake service and verify parseable JSON, text output, warnings, and unavailable reports.

### Tests for User Story 3

- [x] T024 [P] [US3] Write failing CLI registration test for `fixture-information` help in `tests/test_cli.py`
- [x] T025 [P] [US3] Write failing CLI JSON contract test for digest status, summary, items, source count, latest timestamp, and warnings in `tests/test_cli.py`
- [x] T026 [P] [US3] Write failing CLI test for unavailable information returning parseable JSON without failure in `tests/test_cli.py`

### Implementation for User Story 3

- [x] T027 [US3] Implement `build_fixture_information_service()` in `nutmeg/interfaces/cli.py`
- [x] T028 [US3] Implement `fixture-information` text/JSON CLI command in `nutmeg/interfaces/cli.py`
- [x] T029 [US3] Add README usage examples for `fixture-information` in `README.md`
- [x] T030 [US3] Add `news-information-provider-v0` entry to `feature-list.json`
- [x] T031 [US3] Complete information provider documentation in `docs/architecture/information-provider.md`

**Checkpoint**: User Story 3 is independently usable from CLI and ready for future bot/client reuse.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Finish docs, verification, graph assets, and feature status.

- [x] T032 [P] Add completion notes to `.specify/specs/039-news-information-provider-v0/verification.md`
- [x] T033 [P] Update `docs/architecture/design-gap-audit.md` to mark information provider v0 as closed for local-first scope
- [x] T034 Run focused information/client/CLI tests and record evidence in `.specify/specs/039-news-information-provider-v0/verification.md`
- [x] T035 Run `uv run ruff check .`, `python3 -m compileall nutmeg`, and `bash scripts/verify.sh`, then record evidence in `.specify/specs/039-news-information-provider-v0/verification.md`
- [x] T036 Refresh graph assets with `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` and review `graphify-out/GRAPH_REPORT.md`
- [x] T037 Update `memory/2026-04-26.md` and `agent-progress.md` with implementation rationale and verification evidence
- [x] T038 Mark `.specify/specs/039-news-information-provider-v0/spec.md` status according to final verification result

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1; blocks all user stories.
- **Phase 3 US1**: Depends on Phase 2; MVP information ingestion.
- **Phase 4 US2**: Depends on US1 digest payloads.
- **Phase 5 US3**: Depends on US1 service and can complete after CLI builder exists.
- **Phase 6 Polish**: Depends on all implemented stories.

### Within Each User Story

- Write failing tests first.
- Implement only enough behavior to make failing tests pass.
- Keep rumor/unverified labels visible.
- Do not add network scraping or paid APIs in v0.

## Parallel Opportunities

- T002 and T003 can run in parallel after T001.
- T004 and T006 can run in parallel because both are test-only tasks.
- US1 test tasks T008 through T011 can be written together before implementation.
- US2 test tasks T016 through T018 can be written together before implementation.
- US3 test tasks T024 through T026 can be written together before implementation.
- Polish tasks T032 and T033 can run in parallel.
