# Tasks: Zucai Odds Source v0

**Input**: Design documents from `.specify/specs/044-zucai-odds-source-v0/`  
**Tests**: Required. Nutmeg constitution requires Superpowers/TDD.

## Phase 1: Setup

- [x] T001 Create bundled afternoon/revision odds source samples in `nutmeg/zucai/samples/`
- [x] T002 [P] Create architecture doc stub in `docs/architecture/zucai-odds-source.md`
- [x] T003 [P] Create verification placeholder in `.specify/specs/044-zucai-odds-source-v0/verification.md`

## Phase 2: Parser Foundation

- [x] T004 [P] Write failing parser/service tests in `tests/test_zucai_odds_source_service.py`
- [x] T005 Implement odds sync dataclass in `nutmeg/domain/zucai_odds_source.py`
- [x] T006 Implement local odds parsing and validation in `nutmeg/services/zucai_odds_source.py`

## Phase 3: Snapshot and Registry Sync

- [x] T007 [P] Write failing tests for odds snapshot writing and registry field preservation in `tests/test_zucai_odds_source_service.py`
- [x] T008 Implement odds snapshot writing in `nutmeg/services/zucai_odds_source.py`
- [x] T009 Implement registry update for `odds_file` and `revision_odds_file` in `nutmeg/services/zucai_odds_source.py`
- [x] T010 Add generated-registry `zucai-auto-run` revision integration test in `tests/test_zucai_odds_source_service.py`

## Phase 4: CLI and Safety

- [x] T011 [P] Write failing CLI tests for local odds sync and URL-without-live-fetch rejection in `tests/test_cli.py`
- [x] T012 Implement `zucai-odds-sync` CLI command in `nutmeg/interfaces/cli.py`
- [x] T013 Implement opt-in bounded live fetch path in `nutmeg/services/zucai_odds_source.py`

## Phase 5: Docs and Verification

- [x] T014 Complete docs in `docs/architecture/zucai-odds-source.md` and README
- [x] T015 Add `zucai-odds-source-v0` to `feature-list.json`
- [x] T016 Update `agent-progress.md` and `memory/2026-04-26.md`
- [x] T017 Run focused parser/CLI tests and record RED/GREEN evidence
- [x] T018 Run CLI smokes for source sync -> odds sync -> auto-run
- [x] T019 Run `uv run ruff check .`, `python3 -m compileall nutmeg scripts/openclaw`, and `bash scripts/verify.sh`
- [x] T020 Refresh graph assets and review `graphify-out/GRAPH_REPORT.md`

## Dependencies

- Parser foundation before snapshot/registry.
- Snapshot/registry before generated-registry auto-run integration.
- CLI after service behavior exists.
- Verification after all implementation/docs.
