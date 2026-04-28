# Verification: Traditional Zucai 14-Match Workflow v0

Date: 2026-04-26  
Feature: `.specify/specs/041-zucai-14match-workflow-v0`

## RED Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_service.py tests/test_telegram_bot.py::test_telegram_client_sends_document_without_leaking_token_in_path_body tests/test_cli.py::test_zucai_report_command_generates_json_artifacts_and_dry_run_dispatch tests/test_cli.py::test_zucai_report_command_rejects_invalid_issue tests/test_cli.py::test_zucai_grade_command_returns_plan_coverage -q`
  - Result before implementation: collection failed with `ModuleNotFoundError: No module named 'nutmeg.services.zucai'`.
  - Expected failure: Zucai service/domain did not exist yet.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_openclaw_router.py::test_router_builds_zucai_report_command_and_requires_dispatch_confirmation -q`
  - Result before router implementation: failed with `RouterError: Unsupported action 'zucai-report'`.
  - Expected failure: OpenClaw router had no Zucai action.

## GREEN / Focused Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_service.py tests/test_telegram_bot.py::test_telegram_client_sends_document_without_leaking_token_in_path_body tests/test_cli.py::test_zucai_report_command_generates_json_artifacts_and_dry_run_dispatch tests/test_cli.py::test_zucai_report_command_rejects_invalid_issue tests/test_cli.py::test_zucai_grade_command_returns_plan_coverage -q`
  - Result: `11 passed`.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_openclaw_router.py::test_router_builds_zucai_report_command_and_requires_dispatch_confirmation -q`
  - Result: `1 passed`.
- Focused Zucai/CLI/Telegram/router suite:
  - Command: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_service.py tests/test_cli.py tests/test_telegram_bot.py tests/test_openclaw_router.py -q`
  - Result: passed; output showed all selected tests completed (`100%`).

## CLI / Packaging Evidence

- `uv run nutmeg zucai-report --issue-id 26068 --output-dir .nutmeg-data/zucai-smoke --pdf --format json`
  - Result: exit 0; issue `26068`, 14 recommendations, plans `均衡主推` (`1024`注 / `2048`元) and `任九稳妥` (`32`注 / `64`元), PDF header `%PDF`.
- `uv run nutmeg zucai-grade --report-file .nutmeg-data/zucai-smoke/zucai-26068-report.json --outcomes-file nutmeg/zucai/samples/26068-outcomes.json --format json`
  - Result: exit 0; 14 match results; sample plans covered (`均衡主推` 14/14, `任九稳妥` 9/9) using bundled sample outcomes.
- `python3 scripts/openclaw/nutmeg_command_router.py --print-command zucai-report --issue-id 26068 --pdf`
  - Result: exit 0; generated `uv run nutmeg zucai-report --issue-id 26068 --output-dir .nutmeg-data/zucai --pdf --format json`.
- `python3 scripts/openclaw/nutmeg_command_router.py zucai-report --issue-id 26068 --pdf`
  - Result: exit 0; router envelope `ok=true`, payload issue `26068`, 14 recommendations.
- `uv build --wheel` plus wheel inspection
  - Result: built `nutmeg-0.2.0-py3-none-any.whl`; bundled Zucai sample files missing list was empty.

## Full Verification Evidence

- `uv run ruff check .`
  - Result: `All checks passed!`
- `python3 -m compileall nutmeg scripts/openclaw`
  - Result: exit 0; compiled Nutmeg and OpenClaw scripts including new `nutmeg/zucai` package.
- `bash scripts/verify.sh`
  - Result: `283 passed in 3.75s`.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out`
  - Result: graph refreshed to 90 modules / 138 internal dependency edges.

## Spec Verification Checklist

- [x] R01: Zucai issue model with issue id, sale window, draw date, sources, and exactly 14 matches — verified by `tests/test_zucai_service.py`.
- [x] R02: Invalid issue match count/numbering rejected — verified by `test_zucai_service_rejects_issue_without_exactly_14_matches` and CLI invalid issue test.
- [x] R03: Latest odds snapshot attached where available — verified by `test_zucai_service_loads_issue_odds_and_overrides`.
- [x] R04: One recommendation per match with pick/primary/confidence/risk/rationale — verified by sample report CLI smoke and service tests.
- [x] R05: Analyst overrides supported with invalid override warnings — verified by override tests and bundled 26068 overrides.
- [x] R06: Full14 and 任九 plans generated with stake counts and cost — verified by service tests and CLI smoke.
- [x] R07: `zucai-report` JSON CLI contract works — verified by CLI tests and smoke.
- [x] R08: Markdown artifact written — verified by service artifact test.
- [x] R09: PDF artifact written when requested and failures labeled — verified by service/CLI PDF header tests.
- [x] R10: Telegram document dispatch is dry-run by default and does not leak tokens — verified by Telegram client test and CLI dry-run dispatch test.
- [x] R11: `zucai-grade` JSON CLI contract works — verified by service and CLI grading tests.
- [x] R12: Documentation explains workflow and responsible-use boundaries — verified by `docs/architecture/zucai-14match-workflow.md`, README, integration docs, and OpenClaw workspace instructions.
- [x] R13: Bundled 26068 sample supports no-network smoke — verified by `zucai-report --issue-id 26068` smoke and wheel inspection.
