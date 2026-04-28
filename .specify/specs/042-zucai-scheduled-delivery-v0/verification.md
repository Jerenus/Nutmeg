# Verification: Zucai Scheduled Delivery v0

Date: 2026-04-26  
Feature: `.specify/specs/042-zucai-scheduled-delivery-v0`

## RED Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_schedule_service.py tests/test_cli.py::test_zucai_auto_run_command_skips_no_issue tests/test_cli.py::test_zucai_auto_run_command_generates_afternoon_report tests/test_cli.py::test_zucai_auto_run_command_duplicate_and_force -q`
  - Result before implementation: collection failed with `ModuleNotFoundError: No module named 'nutmeg.services.zucai_schedule'`.
  - Expected failure: scheduled delivery domain/service and CLI command did not exist yet.

## GREEN / Focused Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_schedule_service.py tests/test_cli.py::test_zucai_auto_run_command_skips_no_issue tests/test_cli.py::test_zucai_auto_run_command_generates_afternoon_report tests/test_cli.py::test_zucai_auto_run_command_duplicate_and_force -q`
  - Result: `11 passed`.
- `uv run ruff check nutmeg/domain/zucai_schedule.py nutmeg/services/zucai_schedule.py nutmeg/services/zucai.py nutmeg/interfaces/cli.py tests/test_zucai_schedule_service.py tests/test_cli.py`
  - Result: `All checks passed!` after line-length/import cleanup.

## CLI Smoke Evidence

Smoke directory: `.nutmeg-data/zucai-042-smoke-1XqO4Y`

- No-issue day:
  - Command: `uv run nutmeg zucai-auto-run --date 2026-04-27 --slot afternoon --registry-file nutmeg/zucai/samples/scheduled-issues.json --output-dir <smoke>/scheduled --run-record-file <smoke>/records.json --format json`
  - Result: status `skipped_no_issue`, issue `None`, dispatch `skipped`.
- Afternoon first report:
  - Command: `uv run nutmeg zucai-auto-run --date 2026-04-26 --slot afternoon --registry-file nutmeg/zucai/samples/scheduled-issues.json --output-dir <smoke>/scheduled --run-record-file <smoke>/records.json --dispatch-telegram --dry-run --format json`
  - Result: status `dry_run`, issue `26068`, dispatch `dry_run`, PDF header `%PDF`.
- Revision confirmation report:
  - Command: `uv run nutmeg zucai-auto-run --date 2026-04-26 --slot revision --registry-file nutmeg/zucai/samples/scheduled-issues.json --output-dir <smoke>/scheduled --run-record-file <smoke>/records.json --dispatch-telegram --dry-run --format json`
  - Result: status `dry_run`, issue `26068`, dispatch `dry_run`, PDF header `%PDF`.
- Duplicate revision run:
  - Result: status `skipped_duplicate`, dispatch `skipped`.
- Force revision rerun:
  - Result: status `dry_run`, PDF header `%PDF`.
- Run records:
  - Result: three active records: `afternoon dry_run`, `revision dry_run`, `revision dry_run` for the forced rerun. The no-issue run did not create a blocking record.

## Full Verification Evidence

- `uv run ruff check .`
  - Result: `All checks passed!`
- `python3 -m compileall nutmeg scripts/openclaw`
  - Result: exit 0; compiled Nutmeg and OpenClaw modules including `nutmeg/domain/zucai_schedule.py` and `nutmeg/services/zucai_schedule.py`.
- `bash scripts/verify.sh`
  - Result: `294 passed in 3.84s`.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out`
  - Result: graph refreshed to `92 modules / 143 edges`; `graphify-out/GRAPH_REPORT.md` reviewed.
- `uv build --wheel` plus wheel inspection
  - Result: built `nutmeg-0.2.0-py3-none-any.whl`; `nutmeg/zucai/samples/scheduled-issues.json` was included, missing list `[]`.

## Spec Verification Checklist

- [x] R01: `zucai-auto-run` accepts date, slot, registry, output, run-record, dispatch, dry-run, and force options — verified by `tests/test_cli.py` Zucai auto-run tests.
- [x] R02: Only `afternoon` and `revision` slots are supported — verified by `test_schedule_service_rejects_unknown_slot`.
- [x] R03: Local registry finds enabled active issues — verified by active afternoon/revision service tests.
- [x] R04: No active issue skips with no PDF and no dispatch — verified by `test_schedule_service_skips_no_issue_without_dispatch_or_artifacts` and CLI no-issue test.
- [x] R05: Relative registry paths resolve correctly — verified by sample-copy registry tests using registry-relative paths.
- [x] R06: Scheduled generation reuses `ZucaiWorkflowService` — verified structurally by `ZucaiScheduledDeliveryService(workflow_service=...)` and active report tests.
- [x] R07: Slot-specific artifacts prevent overwrites — verified by `test_schedule_service_revision_uses_separate_artifacts_and_caption`.
- [x] R08: Run records capture active attempts — verified by active and duplicate/force service tests.
- [x] R09: Duplicate runs skip unless forced — verified by `test_schedule_service_skips_duplicate_and_force_regenerates` and CLI duplicate/force test.
- [x] R10: Revision-specific overrides are supported — verified by `test_schedule_service_revision_uses_revision_specific_overrides`.
- [x] R11: Telegram captions include slot labels — verified by afternoon/revision caption assertions.
- [x] R12: Telegram dispatch remains dry-run by default and real sends require explicit flags — verified by CLI/service dry-run tests and launchd template inspection.
- [x] R13: 16:00 and 18:30 scheduler templates exist — verified by `test_launchd_templates_call_expected_slots_and_times`.
- [x] R14: Enablement/troubleshooting docs exist — verified by `docs/architecture/zucai-scheduled-delivery.md` and README updates.
- [x] R15: Responsible-use boundaries remain intact — verified by docs, captions, and absence of betting execution/sportsbook integration.
