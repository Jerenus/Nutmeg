# Tasks: Content Publisher v0

**Input**: Design documents from `.specify/specs/045-content-publisher-v0/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli-contract.md`, `quickstart.md`

**Tests**: Required. Nutmeg constitution requires TDD; every behavior change starts with failing tests before implementation.

## Phase 1: Setup

- [x] T001 Create bundled content report sample in `nutmeg/content/samples/26068-content-report.json`
- [x] T002 [P] Create architecture doc stub in `docs/architecture/content-publisher.md`
- [x] T003 [P] Create verification placeholder in `.specify/specs/045-content-publisher-v0/verification.md`

## Phase 2: Foundational Domain and Compliance

- [x] T004 [P] [US3] Write failing compliance risk tests in `tests/test_content_service.py`
- [x] T005 Implement content dataclasses in `nutmeg/domain/content.py`
- [x] T006 Implement deterministic compliance checker in `nutmeg/services/content.py`

## Phase 3: User Story 1 - Select publish-worthy matches (Priority: P1)

- [x] T007 [P] [US1] Write failing candidate scoring/ranking tests in `tests/test_content_service.py`
- [x] T008 [US1] Implement Zucai report loading and content candidate scoring in `nutmeg/services/content.py`

## Phase 4: User Story 2 - Generate validated multi-format content (Priority: P1)

- [x] T009 [P] [US2] Write failing LLM output parsing/disclaimer enforcement tests in `tests/test_content_service.py`
- [x] T010 [P] [US2] Write failing OpenClaw provider payload extraction tests in `tests/test_content_service.py`
- [x] T011 [US2] Implement LLM prompt builder, JSON extraction, safe fallback draft, and OpenClaw provider adapter in `nutmeg/services/content.py`
- [x] T012 [US2] Implement content pack generation with post-generation compliance gate in `nutmeg/services/content.py`

## Phase 5: User Story 4 - CLI and artifacts (Priority: P2)

- [x] T013 [P] [US4] Write failing CLI JSON/artifact test for `content-pack` in `tests/test_cli.py`
- [x] T014 [P] [US4] Write failing CLI validation test for missing/malformed report in `tests/test_cli.py`
- [x] T015 [US4] Implement `content-pack` service builder and CLI command in `nutmeg/interfaces/cli.py`
- [x] T016 [US4] Implement JSON and Markdown artifact writing in `nutmeg/services/content.py`

## Phase 6: Docs, Registry, and Verification

- [x] T017 Complete architecture docs in `docs/architecture/content-publisher.md`
- [x] T018 Update README with content publisher workflow examples in `README.md`
- [x] T019 Add `content-publisher-v0` entry to `feature-list.json`
- [x] T020 Update `agent-progress.md`, `AGENTS.md`, and `memory/2026-04-26.md` with rationale and verification evidence
- [x] T021 Run focused content service/CLI tests and record RED/GREEN evidence in `.specify/specs/045-content-publisher-v0/verification.md`
- [x] T022 Run deterministic CLI smoke and OpenClaw model smoke, then record evidence in `.specify/specs/045-content-publisher-v0/verification.md`
- [x] T023 Run `uv run ruff check .`, `python3 -m compileall nutmeg scripts/openclaw`, and `bash scripts/verify.sh`, then record evidence in `.specify/specs/045-content-publisher-v0/verification.md`
- [x] T024 Refresh graph assets with `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` and review `graphify-out/GRAPH_REPORT.md`

## Dependencies

- Phase 1 before implementation.
- Phase 2 compliance foundation before LLM content can be trusted.
- US1 candidate scoring before US2 generation.
- US2 generation before US4 CLI artifacts.
- Verification after all code/docs tasks.

## Implementation Strategy

1. MVP foundation: compliance checker and domain contracts.
2. Selection: deterministic candidate scoring from Zucai report JSON.
3. Generation: OpenClaw LLM adapter plus schema validation/disclaimer enforcement.
4. Handoff: JSON/Markdown artifacts and CLI output.
5. Polish: docs, feature registry, memory, graph, and full verification.
