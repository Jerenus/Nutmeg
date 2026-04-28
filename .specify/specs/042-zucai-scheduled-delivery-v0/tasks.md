# Tasks: Zucai Scheduled Delivery v0

**Input**: Design documents from `.specify/specs/042-zucai-scheduled-delivery-v0/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli-contract.md`, JSON schemas, `quickstart.md`

**Tests**: Required. Nutmeg constitution requires Superpowers/TDD; every behavior change starts with failing tests before implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and does not depend on incomplete tasks.
- **[Story]**: Maps to `[US1]`, `[US2]`, `[US3]`, or `[US4]` in `spec.md`.
- Every task names exact file paths.

## Phase 1: Setup

- [x] T001 Create bundled scheduled issue registry sample in `nutmeg/zucai/samples/scheduled-issues.json`
- [x] T002 [P] Create Zucai scheduled delivery architecture doc stub in `docs/architecture/zucai-scheduled-delivery.md`
- [x] T003 [P] Create verification log placeholder in `.specify/specs/042-zucai-scheduled-delivery-v0/verification.md`

## Phase 2: Foundational

- [x] T004 [P] Write failing domain/service tests for registry loading, slot validation, path resolution, and no-issue skipping in `tests/test_zucai_schedule_service.py`
- [x] T005 Implement scheduled Zucai dataclasses and serialization helpers in `nutmeg/domain/zucai_schedule.py`
- [x] T006 Implement registry loading, active issue selection, slot validation, and no-issue result in `nutmeg/services/zucai_schedule.py`

## Phase 3: User Story 1 - Run the scheduled issue check silently (Priority: P1)

**Goal**: Scheduled runs skip quietly when no active issue exists.

**Independent Test**: Use an empty/missing registry and verify `skipped_no_issue`, no artifacts, no dispatch, exit 0.

- [x] T007 [P] [US1] Write failing service tests for missing registry and malformed/disabled entry warnings in `tests/test_zucai_schedule_service.py`
- [x] T008 [P] [US1] Write failing CLI JSON test for `zucai-auto-run` no-issue skip in `tests/test_cli.py`
- [x] T009 [US1] Implement missing/malformed registry tolerance in `nutmeg/services/zucai_schedule.py`
- [x] T010 [US1] Add `zucai-auto-run` CLI no-issue path in `nutmeg/interfaces/cli.py`

## Phase 4: User Story 2 - Generate and send the 16:00 first report (Priority: P1)

**Goal**: Afternoon slot generates slot-specific artifacts and dispatch metadata using the existing Zucai report workflow.

**Independent Test**: Run `afternoon` against sample registry and verify JSON/Markdown/PDF artifacts, dry-run dispatch, and run record.

- [x] T011 [P] [US2] Write failing service test for active afternoon generation, dry-run dispatch, and run record in `tests/test_zucai_schedule_service.py`
- [x] T012 [P] [US2] Write failing CLI JSON test for active afternoon generation in `tests/test_cli.py`
- [x] T013 [US2] Implement active issue orchestration and slot-specific output directories in `nutmeg/services/zucai_schedule.py`
- [x] T014 [US2] Implement run record persistence in `nutmeg/services/zucai_schedule.py`
- [x] T015 [US2] Wire active `zucai-auto-run` CLI options and JSON/text output in `nutmeg/interfaces/cli.py`

## Phase 5: User Story 3 - Generate the 18:30 revised confirmation report (Priority: P1)

**Goal**: Revision slot is separate from afternoon and can use revision-specific snapshots.

**Independent Test**: Run afternoon then revision for the same issue and verify distinct artifact directories, record entries, and revision caption.

- [x] T016 [P] [US3] Write failing service test for separate revision slot artifacts and revision caption in `tests/test_zucai_schedule_service.py`
- [x] T017 [P] [US3] Write failing service test for revision-specific odds/override path selection in `tests/test_zucai_schedule_service.py`
- [x] T018 [US3] Implement revision-specific file selection and caption labeling in `nutmeg/services/zucai_schedule.py`

## Phase 6: Duplicate Prevention and Force Mode

- [x] T019 [P] Write failing service test for duplicate skip and force regeneration in `tests/test_zucai_schedule_service.py`
- [x] T020 Implement duplicate detection and force mode in `nutmeg/services/zucai_schedule.py`
- [x] T021 Add CLI `--force` behavior coverage in `tests/test_cli.py`

## Phase 7: User Story 4 - Installable schedule templates (Priority: P2)

**Goal**: Provide launchd templates for 16:00 and 18:30 scheduled runs.

**Independent Test**: Inspect templates for slot names, times, project working directory, and real dispatch flags.

- [x] T022 [P] [US4] Write failing template test in `tests/test_zucai_schedule_service.py`
- [x] T023 [US4] Create launchd templates in `scripts/launchd/com.nutmeg.zucai.afternoon.plist` and `scripts/launchd/com.nutmeg.zucai.revision.plist`

## Phase 8: Docs, Registry, and Verification

- [x] T024 Complete architecture docs in `docs/architecture/zucai-scheduled-delivery.md`
- [x] T025 Update README Zucai scheduled usage examples in `README.md`
- [x] T026 Add `zucai-scheduled-delivery-v0` entry to `feature-list.json`
- [x] T027 Update `agent-progress.md` and `memory/2026-04-26.md` with rationale and verification evidence
- [x] T028 Run focused Zucai scheduled tests and record RED/GREEN evidence in `.specify/specs/042-zucai-scheduled-delivery-v0/verification.md`
- [x] T029 Run CLI smokes for no-issue, afternoon, revision, duplicate, and force scenarios and record evidence in `.specify/specs/042-zucai-scheduled-delivery-v0/verification.md`
- [x] T030 Run `uv run ruff check .`, `python3 -m compileall nutmeg scripts/openclaw`, and `bash scripts/verify.sh`, then record evidence in `.specify/specs/042-zucai-scheduled-delivery-v0/verification.md`
- [x] T031 Refresh graph assets with `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` and review `graphify-out/GRAPH_REPORT.md`

## Dependencies

- Phase 1 before implementation.
- Phase 2 before all user stories.
- US1 must complete before active-generation stories because no-issue safety is the scheduler default.
- US2 before US3 because revision reuses active-generation mechanics.
- Duplicate prevention after active-generation records exist.
- Launchd templates after CLI semantics are stable.
- Verification after all code/docs tasks.

## Implementation Strategy

1. MVP: registry loading and no-issue silent skip.
2. Delivery: active issue generation, PDF, dry-run/real Telegram dispatch, and records.
3. Revision: separate 18:30 slot with slot-specific data support.
4. Reliability: duplicate prevention, force mode, docs, launchd templates, and full verification.
