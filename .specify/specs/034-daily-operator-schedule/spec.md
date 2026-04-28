# Feature Specification: Daily Operator Schedule

**Feature Branch**: `034-daily-operator-schedule`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Close the Sprint 6 daily incremental data pull and weekly push gap.

## User Scenarios & Testing

### User Story 1 - Run one daily operator cycle (Priority: P1)

As the operator, I want one command to sync fixtures, rank popular/value matches,
and optionally build briefs so daily use does not require remembering many CLI calls.

### User Story 2 - Dry-run before live dispatch (Priority: P1)

As the operator, I want safe dry-run output for every scheduled action before any
message is sent to Telegram.

### User Story 3 - Push concise weekly schedule (Priority: P2)

As the operator, I want a weekly schedule summary pushed through the bot transport
when explicitly enabled.

## Functional Requirements

- **FR-001**: Provide `daily-run` text/JSON CLI.
- **FR-002**: Chain existing fixture sync, popular matches, value board, and optional match briefs.
- **FR-003**: Default to dry-run/no Telegram send.
- **FR-004**: Require explicit flag for Telegram dispatch.
- **FR-005**: Record cycle summary and failures without hiding partial success.

## Verification Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_operations_service.py tests/test_cli.py::test_daily_run_command_returns_json_contract -q` -> 2 passed.
- Focused new-feature suite with `tests/test_cli.py` -> 57 passed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` -> pass.
- `uv run ruff check .` -> pass.
- `python3 -m compileall nutmeg` -> pass.
- `bash scripts/verify.sh` -> 171 passed.
- `uv run nutmeg daily-run --league epl --days 0 --limit 3 --format json` -> JSON smoke pass.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` -> 72 modules, 115 edges.
