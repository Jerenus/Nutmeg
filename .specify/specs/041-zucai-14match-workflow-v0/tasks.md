# Tasks: Traditional Zucai 14-Match Workflow v0

**Input**: Design documents from `.specify/specs/041-zucai-14match-workflow-v0/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli-contract.md`, JSON schemas, `quickstart.md`

**Tests**: Required. Nutmeg constitution requires Superpowers/TDD; every behavior change starts with failing tests before implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and does not depend on incomplete tasks
- **[Story]**: Maps to `[US1]`, `[US2]`, or `[US3]` in `spec.md`
- Every task names exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add samples and documentation placeholders before behavior.

- [x] T001 Create bundled 26068 issue/odds/overrides/outcomes samples in `nutmeg/zucai/samples/`
- [x] T002 [P] Add Zucai architecture doc stub in `docs/architecture/zucai-14match-workflow.md`
- [x] T003 [P] Add 041 verification placeholder in `.specify/specs/041-zucai-14match-workflow-v0/verification.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish domain models and loader validation shared by all stories.

- [x] T004 [P] Write failing domain/service tests for issue validation and odds/override normalization in `tests/test_zucai_service.py`
- [x] T005 Implement Zucai dataclasses and serialization helpers in `nutmeg/domain/zucai.py`
- [x] T006 Implement JSON loading and issue/odds/override validation in `nutmeg/services/zucai.py`

**Checkpoint**: Zucai issue snapshots can be loaded and validated without recommendations.

---

## Phase 3: User Story 1 - Build a reusable 14-match issue report (Priority: P1) 🎯 MVP

**Goal**: Build a report payload with 14 recommendations, odds evidence, overrides, plans, warnings, and source ledger.

**Independent Test**: Build a report from temp issue/odds/overrides files and verify recommendations/plans/warnings.

### Tests for User Story 1

- [x] T007 [P] [US1] Write failing report-generation test in `tests/test_zucai_service.py`
- [x] T008 [P] [US1] Write failing invalid-issue rejection test in `tests/test_zucai_service.py`
- [x] T009 [P] [US1] Write failing invalid override warning test in `tests/test_zucai_service.py`

### Implementation for User Story 1

- [x] T010 [US1] Implement baseline recommendation generation in `nutmeg/services/zucai.py`
- [x] T011 [US1] Implement override application and invalid override warnings in `nutmeg/services/zucai.py`
- [x] T012 [US1] Implement full14 and 任九 plan generation with stake counts in `nutmeg/services/zucai.py`
- [x] T013 [US1] Add bundled sample lookup for issue id 26068 in `nutmeg/services/zucai.py`

**Checkpoint**: US1 can generate a reusable 14-match report payload.

---

## Phase 4: User Story 2 - Render and deliver reusable artifacts (Priority: P1)

**Goal**: Write Markdown/PDF artifacts and safely dry-run or send Telegram document delivery.

**Independent Test**: Render a sample report to a temp output directory and verify artifact paths, PDF header, and dry-run dispatch payload.

### Tests for User Story 2

- [x] T014 [P] [US2] Write failing Markdown/PDF rendering test in `tests/test_zucai_service.py`
- [x] T015 [P] [US2] Write failing Telegram document sender test in `tests/test_telegram_bot.py`
- [x] T016 [P] [US2] Write failing CLI dry-run dispatch test in `tests/test_cli.py`

### Implementation for User Story 2

- [x] T017 [US2] Add `reportlab` dependency to `pyproject.toml` and `uv.lock`
- [x] T018 [US2] Implement Markdown and PDF rendering in `nutmeg/services/zucai.py`
- [x] T019 [US2] Add `TelegramBotClient.send_document()` in `nutmeg/interfaces/bot/telegram.py`
- [x] T020 [US2] Implement dispatch status handling in `nutmeg/services/zucai.py`
- [x] T021 [US2] Add `zucai-report` CLI command in `nutmeg/interfaces/cli.py`

**Checkpoint**: US2 can archive and deliver a generated issue report.

---

## Phase 5: User Story 3 - Review issue results after settlement (Priority: P2)

**Goal**: Grade saved reports against outcome files for match and plan coverage.

**Independent Test**: Grade a report JSON with complete and incomplete outcome files and verify hit counts and warnings.

### Tests for User Story 3

- [x] T022 [P] [US3] Write failing service grading test in `tests/test_zucai_service.py`
- [x] T023 [P] [US3] Write failing `zucai-grade` CLI JSON test in `tests/test_cli.py`

### Implementation for User Story 3

- [x] T024 [US3] Implement outcome loading and grade report generation in `nutmeg/services/zucai.py`
- [x] T025 [US3] Add `zucai-grade` CLI command in `nutmeg/interfaces/cli.py`

**Checkpoint**: US3 can close the loop for settled issues.

---

## Phase 6: Bot/Docs/Registry Polish

**Purpose**: Make the feature discoverable and bot-ready.

- [x] T026 Extend OpenClaw safe router with a `zucai-report` action in `scripts/openclaw/nutmeg_command_router.py`
- [x] T027 [P] Add router test for `zucai-report` command mapping and dispatch confirmation in `tests/test_openclaw_router.py`
- [x] T028 [P] Complete Zucai architecture docs in `docs/architecture/zucai-14match-workflow.md`
- [x] T029 [P] Update README Zucai usage examples in `README.md`
- [x] T030 Add `zucai-14match-workflow-v0` entry to `feature-list.json`
- [x] T031 Update `agent-progress.md` and `memory/2026-04-26.md` with rationale and verification evidence

---

## Phase 7: Verification

**Purpose**: Prove the feature and neighboring workflows remain reliable.

- [x] T032 Run focused Zucai, CLI, Telegram, and router tests and record evidence in `.specify/specs/041-zucai-14match-workflow-v0/verification.md`
- [x] T033 Run sample CLI smokes for `zucai-report` and `zucai-grade`, then record outputs in `.specify/specs/041-zucai-14match-workflow-v0/verification.md`
- [x] T034 Run `uv run ruff check .`, `python3 -m compileall nutmeg`, and `bash scripts/verify.sh`, then record evidence in `.specify/specs/041-zucai-14match-workflow-v0/verification.md`
- [x] T035 Refresh graph assets with `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` and review `graphify-out/GRAPH_REPORT.md`

## Dependencies

- Phase 1 before all implementation.
- Phase 2 before all user stories.
- US1 before US2 and US3 because artifact rendering and grading need the report payload.
- US2 before router/docs finalization because bot usage depends on CLI behavior.
- Verification after all feature and docs tasks.

## Implementation Strategy

1. MVP: complete Phase 1-3 to generate reusable report JSON from local snapshots.
2. Delivery: add artifacts, PDF, Telegram dry-run/send, and CLI.
3. Review: add grading.
4. Polish: router/docs/registry and full verification.
