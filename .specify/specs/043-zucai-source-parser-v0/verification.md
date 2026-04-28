# Verification: Zucai Source Parser v0

Date: 2026-04-26  
Feature: `.specify/specs/043-zucai-source-parser-v0`

## RED Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_source_service.py tests/test_cli.py::test_zucai_source_sync_command_generates_registry tests/test_cli.py::test_zucai_source_sync_command_rejects_url_without_live_fetch -q`
  - Result before implementation: collection failed with `ModuleNotFoundError: No module named 'nutmeg.services.zucai_source'`.
  - Expected failure: source parser domain/service and CLI command did not exist yet.

## GREEN / Focused Evidence

- Initial GREEN run exposed an expected parser edge bug:
  - `test_source_parser_warns_and_skips_malformed_14_match_section` failed because malformed sections without `序号` were filtered out before warning generation.
  - Root cause fixed by accepting sections that include `第<issue>期` detail markers, then validating exactly 14 rows.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_source_service.py tests/test_cli.py::test_zucai_source_sync_command_generates_registry tests/test_cli.py::test_zucai_source_sync_command_rejects_url_without_live_fetch -q`
  - Result: `8 passed`.
- `uv run ruff check nutmeg/domain/zucai_source.py nutmeg/services/zucai_source.py nutmeg/interfaces/cli.py tests/test_zucai_source_service.py tests/test_cli.py`
  - Result: `All checks passed!` after import/order and line-length cleanup.

## CLI Smoke Evidence

Smoke directory: `.nutmeg-data/zucai-043-smoke-hifWko`

- Source sync:
  - Command: `uv run nutmeg zucai-source-sync --source-file nutmeg/zucai/samples/26068-source-notice.html --date 2026-04-26 --output-dir <smoke>/zucai --registry-file <smoke>/zucai/issues.json --format json`
  - Result: parsed count `1`, active issue ids `['26068']`, registry exists, generated issue has 14 matches.
- Generated-registry auto-run:
  - Command: `uv run nutmeg zucai-auto-run --date 2026-04-26 --slot afternoon --registry-file <smoke>/zucai/issues.json --output-dir <smoke>/scheduled --run-record-file <smoke>/scheduled-runs.json --dispatch-telegram --dry-run --format json`
  - Result: status `dry_run`, issue `26068`, PDF header `%PDF`.

## Full Verification Evidence

- `uv run ruff check .`
  - Result: `All checks passed!`
- `python3 -m compileall nutmeg scripts/openclaw`
  - Result: exit 0; compiled Nutmeg and OpenClaw modules including source parser modules.
- `bash scripts/verify.sh`
  - Result: `302 passed in 3.91s`.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out`
  - Result: graph refreshed to `94 modules / 147 edges`; `graphify-out/GRAPH_REPORT.md` reviewed.
- `uv build --wheel` plus wheel inspection
  - Result: built `nutmeg-0.2.0-py3-none-any.whl`; `nutmeg/zucai/samples/26068-source-notice.html` and `nutmeg/zucai/samples/scheduled-issues.json` included, missing list `[]`.

## Spec Verification Checklist

- [x] R01: `zucai-source-sync` local source CLI exists — verified by CLI source sync test.
- [x] R02: Official-like traditional 14-match sections are parsed — verified by `test_source_parser_extracts_valid_14_match_issue`.
- [x] R03: One valid 14-match snapshot is written per parsed issue — verified by `test_source_sync_writes_issue_snapshot_and_registry`.
- [x] R04: Malformed sections are skipped with warnings — verified by `test_source_parser_warns_and_skips_malformed_14_match_section`.
- [x] R05: Sale start, sale stop, draw date, and source metadata are preserved — verified by parser extraction assertions.
- [x] R06: Active dates are inferred from sale-stop date — verified by registry sync test.
- [x] R07: Scheduled registry is updated with parsed issue file paths — verified by registry sync test and CLI smoke.
- [x] R08: Existing odds/override/revision paths are preserved — verified by `test_source_sync_preserves_existing_registry_operator_paths`.
- [x] R09: JSON CLI output exposes parsed count, written paths, registry, active ids, and warnings — verified by CLI source sync test.
- [x] R10: `--source-url` without `--live-fetch` is rejected — verified by service and CLI validation tests.
- [x] R11: Local-file use makes no default network calls — verified by local-only tests and URL rejection behavior.
- [x] R12: Usage and boundaries are documented — verified by `docs/architecture/zucai-source-parser.md` and README updates.
- [x] R13: Scope stays schedule/registry only with no betting execution — verified by implementation boundaries and docs.
