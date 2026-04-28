# Task Coverage Review: Zucai Scheduled Delivery v0

Date: 2026-04-26  
Feature: `.specify/specs/042-zucai-scheduled-delivery-v0`

## Requirements Extracted

- R01 [TESTABLE]: `zucai-auto-run` accepts date, slot, registry, output, run-record, dispatch, dry-run, and force options.
- R02 [TESTABLE]: Only `afternoon` and `revision` slots are accepted.
- R03 [TESTABLE]: Local issue registry is read to find an enabled issue active for the run date.
- R04 [TESTABLE]: No active issue returns `skipped_no_issue`, creates no PDF, and attempts no Telegram dispatch.
- R05 [TESTABLE]: Relative registry paths resolve relative to registry first, then cwd.
- R06 [STRUCTURAL]: Scheduled generation reuses `ZucaiWorkflowService` instead of duplicating recommendation logic.
- R07 [TESTABLE]: Slot-specific artifacts prevent afternoon/revision overwrites.
- R08 [TESTABLE]: Active runs record run date, slot, issue id, status, artifacts, dispatch, and warnings.
- R09 [TESTABLE]: Duplicate date/slot/issue runs skip unless force is enabled.
- R10 [TESTABLE]: Revision-specific odds and overrides are supported.
- R11 [TESTABLE]: Telegram captions include slot labels.
- R12 [TESTABLE]: Telegram dispatch is dry-run by default; real send requires explicit flags.
- R13 [OBSERVABLE]: Local scheduler templates exist for 16:00 and 18:30.
- R14 [OBSERVABLE]: Workflow docs explain enablement, validation, and troubleshooting.
- R15 [STRUCTURAL]: Responsible-use boundaries remain in docs/captions and no betting execution is introduced.

## Coverage Matrix

| Req | Tasks | Coverage |
| --- | --- | --- |
| R01 | T008, T010, T012, T015, T021 | Covered |
| R02 | T004, T006 | Covered |
| R03 | T004, T006, T007, T009 | Covered |
| R04 | T007, T008, T009, T010 | Covered |
| R05 | T004, T006, T011 | Covered |
| R06 | T011, T013 | Covered |
| R07 | T011, T013, T016, T018 | Covered |
| R08 | T011, T014, T019, T020 | Covered |
| R09 | T019, T020, T021 | Covered |
| R10 | T017, T018 | Covered |
| R11 | T016, T018 | Covered |
| R12 | T011, T012, T015 | Covered |
| R13 | T022, T023 | Covered |
| R14 | T024, T025 | Covered |
| R15 | T024, T025, T030 | Covered |

## Task Quality and TDD Readiness

- Tasks name concrete files.
- Test tasks precede implementation tasks for every behavior change.
- No placeholders or ambiguous implementation instructions remain.
- Duplicate prevention and real dispatch are covered by tests rather than docs alone.
- TDD readiness: READY.

## Status Synchronization

`.specify/scripts/bash/sync-spec-status.sh` is not present in this repository, so status synchronization is recorded manually in `spec.md` during implementation and verification.
