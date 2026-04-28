# Tasks: Live Information Provider v0

**Input**: Design documents from `.specify/specs/040-live-information-provider-v0/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli-contract.md`, `contracts/source-manifest.schema.json`, `quickstart.md`

**Tests**: Required. Nutmeg constitution requires Superpowers/TDD; every behavior change starts with failing tests before implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and does not depend on incomplete tasks
- **[Story]**: Maps to `[US1]`, `[US2]`, or `[US3]` in `spec.md`
- Every task names exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add manifest/cache fixtures and docs placeholders without live behavior.

- [x] T001 Create live information manifest sample in `nutmeg/information/samples/epl-001-sources.json`
- [x] T002 [P] Add live provider documentation section stub in `docs/architecture/information-provider.md`
- [x] T003 [P] Add 040 verification placeholder in `.specify/specs/040-live-information-provider-v0/verification.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish manifest and cache domain structures required by all stories.

- [x] T004 [P] Write failing domain tests for source definitions and cache entry serialization in `tests/test_information_service.py`
- [x] T005 Implement `InformationSourceDefinition` and `InformationCacheEntry` in `nutmeg/domain/information.py`
- [x] T006 [P] Write failing service tests for manifest loading defaults and warnings in `tests/test_information_service.py`
- [x] T007 Implement manifest loading helpers in `nutmeg/services/information.py`

**Checkpoint**: Manifest source definitions can be loaded without network access.

---

## Phase 3: User Story 1 - Configure trusted information sources (Priority: P1)

**Goal**: Operator-approved manifest sources normalize into enabled local/remote source definitions with warnings for invalid entries.

**Independent Test**: Load a manifest with enabled, disabled, local, remote, and malformed entries and verify normalized definitions and warnings.

### Tests for User Story 1

- [x] T008 [P] [US1] Write failing test for enabled local/remote source normalization in `tests/test_information_service.py`
- [x] T009 [P] [US1] Write failing test for disabled/malformed source handling without blocking valid sources in `tests/test_information_service.py`
- [x] T010 [P] [US1] Write failing backward-compatibility test for no-manifest local sample behavior in `tests/test_information_service.py`

### Implementation for User Story 1

- [x] T011 [US1] Implement manifest-backed provider local source loading in `nutmeg/services/information.py`
- [x] T012 [US1] Implement manifest warning propagation into source health and digest warnings in `nutmeg/services/information.py`
- [x] T013 [US1] Preserve 039 default `LocalInformationProvider` behavior in `nutmeg/services/information.py`

**Checkpoint**: US1 is independently usable for trusted local/remote source configuration without live fetch.

---

## Phase 4: User Story 2 - Refresh remote feeds safely with cache fallback (Priority: P1)

**Goal**: Remote sources fetch only when explicitly enabled, write/read cache entries, and fall back to stale cache with warnings.

**Independent Test**: Use fake fetcher and temp cache dir to prove no-network default, live fetch success, fresh cache hit, stale fallback, fetch failure, timeout, and size cap behavior.

### Tests for User Story 2

- [x] T014 [P] [US2] Write failing no-network-default test proving remote URLs are not fetched without live flag in `tests/test_information_service.py`
- [x] T015 [P] [US2] Write failing live-fetch success test for remote RSS/JSON normalization and cache write in `tests/test_information_service.py`
- [x] T016 [P] [US2] Write failing fresh-cache hit test with no fetch call in `tests/test_information_service.py`
- [x] T017 [P] [US2] Write failing stale-cache fallback test after fetch failure with partial warnings in `tests/test_information_service.py`
- [x] T018 [P] [US2] Write failing remote failure/timeout/oversized response tests in `tests/test_information_service.py`

### Implementation for User Story 2

- [x] T019 [US2] Implement injected HTTP fetch result and default bounded fetcher in `nutmeg/services/information.py`
- [x] T020 [US2] Implement remote cache read/write by URL hash in `nutmeg/services/information.py`
- [x] T021 [US2] Implement no-network default and fresh cache behavior in `nutmeg/services/information.py`
- [x] T022 [US2] Implement live fetch success parsing for remote JSON/RSS in `nutmeg/services/information.py`
- [x] T023 [US2] Implement stale-cache fallback, timeout/error/size warnings, and partial source health in `nutmeg/services/information.py`

**Checkpoint**: US2 is independently usable for safe opt-in remote feeds.

---

## Phase 5: User Story 3 - Surface live information through operator and client commands (Priority: P2)

**Goal**: CLI and client commands accept explicit manifest/cache/live-fetch controls and keep JSON output parseable.

**Independent Test**: Invoke CLI commands with fake services/config paths and verify manifest/cache/live flags are passed, output is parseable, and client workspace information uses the manifest-backed provider.

### Tests for User Story 3

- [x] T024 [P] [US3] Write failing CLI JSON test for `fixture-information --sources-config --live-fetch` in `tests/test_cli.py`
- [x] T025 [P] [US3] Write failing CLI unavailable/partial manifest test for `fixture-information` in `tests/test_cli.py`
- [x] T026 [P] [US3] Write failing client-match manifest injection test in `tests/test_cli.py`
- [x] T027 [P] [US3] Write failing client service test for explicit manifest-backed provider payload in `tests/test_client_service.py`

### Implementation for User Story 3

- [x] T028 [US3] Add `build_live_fixture_information_service()` helper in `nutmeg/interfaces/cli.py`
- [x] T029 [US3] Extend `fixture-information` CLI with manifest/cache/live/timeout/size flags in `nutmeg/interfaces/cli.py`
- [x] T030 [US3] Extend `client-match` CLI with explicit information manifest/cache/live flags in `nutmeg/interfaces/cli.py`
- [x] T031 [US3] Ensure client workspace consumes manifest-backed digest without user-state changes in `nutmeg/services/client.py` or CLI wiring
- [x] T032 [US3] Update README live information examples in `README.md`
- [x] T033 [US3] Add `live-information-provider-v0` entry to `feature-list.json`

**Checkpoint**: US3 is independently usable from CLI and ready for bot/client reuse.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Finish docs, verification, graph assets, and feature status.

- [x] T034 [P] Complete live provider/cache/no-scraping docs in `docs/architecture/information-provider.md`
- [x] T035 [P] Update `docs/architecture/design-gap-audit.md` with live information provider status
- [x] T036 Run focused information/client/CLI tests and record evidence in `.specify/specs/040-live-information-provider-v0/verification.md`
- [x] T037 Run `uv run ruff check .`, `python3 -m compileall nutmeg`, and `bash scripts/verify.sh`, then record evidence in `.specify/specs/040-live-information-provider-v0/verification.md`
- [x] T038 Refresh graph assets with `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` and review `graphify-out/GRAPH_REPORT.md`
- [x] T039 Update `memory/2026-04-26.md` and `agent-progress.md` with implementation rationale and verification evidence
- [x] T040 Mark `.specify/specs/040-live-information-provider-v0/spec.md` status according to final verification result

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1; blocks all user stories.
- **Phase 3 US1**: Depends on Phase 2; manifest source configuration MVP.
- **Phase 4 US2**: Depends on US1 source definitions; safe remote fetch/cache behavior.
- **Phase 5 US3**: Depends on US2 provider behavior; CLI/client surfacing.
- **Phase 6 Polish**: Depends on all implemented stories.

### Within Each User Story

- Write failing tests first.
- Implement only enough behavior to make failing tests pass.
- Remote fetch must be opt-in and cache/stale warnings must remain visible.
- Do not add scraping, auth, paid API coupling, or default network calls in v0.

## Parallel Opportunities

- T002 and T003 can run in parallel after T001.
- T004 and T006 can run in parallel because both are test-only tasks.
- T008 through T010 can be written together before US1 implementation.
- T014 through T018 can be written together before US2 implementation.
- T024 through T027 can be written together before US3 implementation.
- T034 and T035 can run in parallel during polish.
