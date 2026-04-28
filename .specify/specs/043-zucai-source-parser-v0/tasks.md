# Tasks: Zucai Source Parser v0

**Input**: Design documents from `.specify/specs/043-zucai-source-parser-v0/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli-contract.md`, result schema, `quickstart.md`

**Tests**: Required. Nutmeg constitution requires Superpowers/TDD; every behavior change starts with failing tests before implementation.

## Phase 1: Setup

- [x] T001 Create bundled official-like source notice sample in `nutmeg/zucai/samples/26068-source-notice.html`
- [x] T002 [P] Create architecture doc stub in `docs/architecture/zucai-source-parser.md`
- [x] T003 [P] Create verification placeholder in `.specify/specs/043-zucai-source-parser-v0/verification.md`

## Phase 2: Foundational Parser

- [x] T004 [P] Write failing parser tests for local source parsing, exact 14-match validation, and malformed section warnings in `tests/test_zucai_source_service.py`
- [x] T005 Implement source sync dataclasses in `nutmeg/domain/zucai_source.py`
- [x] T006 Implement HTML/text normalization and 14-match issue parsing in `nutmeg/services/zucai_source.py`

## Phase 3: User Story 1 - Parse trusted schedule source (Priority: P1)

- [x] T007 [P] [US1] Write failing service test for writing parsed issue snapshots in `tests/test_zucai_source_service.py`
- [x] T008 [US1] Implement issue snapshot writing in `nutmeg/services/zucai_source.py`

## Phase 4: User Story 2 - Generate/update registry (Priority: P1)

- [x] T009 [P] [US2] Write failing registry sync test with active date inference in `tests/test_zucai_source_service.py`
- [x] T010 [P] [US2] Write failing registry preservation test for existing odds/override paths in `tests/test_zucai_source_service.py`
- [x] T011 [US2] Implement registry merge and active issue calculation in `nutmeg/services/zucai_source.py`
- [x] T012 [US2] Add integration test showing generated registry feeds `zucai-auto-run` in `tests/test_zucai_source_service.py`

## Phase 5: User Story 3 - Safe CLI and optional live fetch (Priority: P2)

- [x] T013 [P] [US3] Write failing CLI JSON test for local `zucai-source-sync` in `tests/test_cli.py`
- [x] T014 [P] [US3] Write failing CLI validation test for `--source-url` without `--live-fetch` in `tests/test_cli.py`
- [x] T015 [US3] Implement `zucai-source-sync` CLI command and service builder in `nutmeg/interfaces/cli.py`
- [x] T016 [US3] Implement opt-in bounded HTTP fetch path in `nutmeg/services/zucai_source.py`

## Phase 6: Docs, Registry, and Verification

- [x] T017 Complete architecture docs in `docs/architecture/zucai-source-parser.md`
- [x] T018 Update README Zucai source sync usage examples in `README.md`
- [x] T019 Add `zucai-source-parser-v0` entry to `feature-list.json`
- [x] T020 Update `agent-progress.md` and `memory/2026-04-26.md` with rationale and verification evidence
- [x] T021 Run focused parser/CLI tests and record RED/GREEN evidence in `.specify/specs/043-zucai-source-parser-v0/verification.md`
- [x] T022 Run CLI smokes for source sync and generated-registry auto-run, then record evidence in `.specify/specs/043-zucai-source-parser-v0/verification.md`
- [x] T023 Run `uv run ruff check .`, `python3 -m compileall nutmeg scripts/openclaw`, and `bash scripts/verify.sh`, then record evidence in `.specify/specs/043-zucai-source-parser-v0/verification.md`
- [x] T024 Refresh graph assets with `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` and review `graphify-out/GRAPH_REPORT.md`

## Dependencies

- Phase 1 before implementation.
- Phase 2 before all user stories.
- US1 before US2 because registry entries reference written issue snapshots.
- US2 before generated-registry `zucai-auto-run` integration.
- CLI after service behavior exists.
- Verification after all code/docs tasks.

## Implementation Strategy

1. MVP: parse local official-like source into valid issue snapshots.
2. Registry: merge parsed issues into `issues.json` and preserve manual fields.
3. CLI: expose local source sync and safe live-fetch validation.
4. Polish: docs, registry, graph, and full verification.
