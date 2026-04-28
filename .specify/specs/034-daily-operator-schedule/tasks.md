# Tasks: Daily Operator Schedule

**Input**: `.specify/specs/034-daily-operator-schedule/`
**Prerequisites**: `025-today-briefs`, `028-popular-matches-ranking`, `031-value-board-v0`

- [x] T001 Define daily operation summary models in `nutmeg/domain/operations.py`.
- [x] T002 Add RED service orchestration tests in `tests/test_operations_service.py`.
- [x] T003 Add RED `daily-run` CLI JSON tests in `tests/test_cli.py`.
- [x] T004 Implement daily operation service with dry-run default.
- [x] T005 Wire popular matches, value board, and optional brief fan-out.
- [x] T006 Add explicit Telegram dispatch path guarded by configuration and flags.
- [x] T007 Implement `daily-run` CLI text/JSON rendering.
- [x] T008 Document usage and safe scheduling recommendations.
- [x] T009 Run verification, refresh graph, update memory/progress.
