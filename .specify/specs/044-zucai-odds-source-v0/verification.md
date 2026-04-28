# Verification: Zucai Odds Source v0

Date: 2026-04-26  
Feature: `.specify/specs/044-zucai-odds-source-v0`

## RED Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_odds_source_service.py tests/test_cli.py::test_zucai_odds_sync_command_updates_registry tests/test_cli.py::test_zucai_odds_sync_command_rejects_url_without_live_fetch -q`
  - Result before implementation: collection failed with `ModuleNotFoundError: No module named 'nutmeg.services.zucai_odds_source'`.
  - Expected failure: odds source parser domain/service and CLI command did not exist yet.

## GREEN / Focused Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_zucai_odds_source_service.py tests/test_cli.py::test_zucai_odds_sync_command_updates_registry tests/test_cli.py::test_zucai_odds_sync_command_rejects_url_without_live_fetch -q`
  - Result: `8 passed`.
- Touched-file lint was run during implementation; full lint evidence is below.

## CLI Smoke Evidence

Smoke directory: `.nutmeg-data/zucai-044-smoke-aYwBlD`

- Source sync:
  - Command: `uv run nutmeg zucai-source-sync --source-file nutmeg/zucai/samples/26068-source-notice.html --date 2026-04-26 --output-dir <smoke>/zucai --registry-file <smoke>/zucai/issues.json --format json`
  - Result: active issue ids `['26068']`.
- Afternoon odds sync:
  - Command: `uv run nutmeg zucai-odds-sync --source-file nutmeg/zucai/samples/26068-odds-source-afternoon.html --issue-id 26068 --slot afternoon --captured-at "2026-04-26 16:00 CST" --output-dir <smoke>/zucai --registry-file <smoke>/zucai/issues.json --format json`
  - Result: parsed `14`, wrote `26068-odds.json`, registry `odds_file=26068-odds.json`.
- Revision odds sync:
  - Command: `uv run nutmeg zucai-odds-sync --source-file nutmeg/zucai/samples/26068-odds-source-revision.html --issue-id 26068 --slot revision --captured-at "2026-04-26 18:30 CST" --output-dir <smoke>/zucai --registry-file <smoke>/zucai/issues.json --format json`
  - Result: parsed `14`, wrote `26068-odds-revision.json`, registry `revision_odds_file=26068-odds-revision.json`.
- Revision auto-run:
  - Command: `uv run nutmeg zucai-auto-run --date 2026-04-26 --slot revision --registry-file <smoke>/zucai/issues.json --output-dir <smoke>/scheduled --run-record-file <smoke>/scheduled-runs.json --dispatch-telegram --dry-run --format json`
  - Result: status `dry_run`, issue `26068`, first recommendation odds average `{'3': 2.22, '1': 3.38, '0': 3.18}`, PDF header `%PDF`.

## Full Verification Evidence

- `uv run ruff check .`
  - Result: `All checks passed!`
- `python3 -m compileall nutmeg scripts/openclaw`
  - Result: exit 0; compiled Nutmeg and OpenClaw modules including odds source parser modules.
- `bash scripts/verify.sh`
  - Result: `310 passed in 3.98s`.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out`
  - Result: graph refreshed to `96 modules / 150 edges`; `graphify-out/GRAPH_REPORT.md` reviewed.
- `uv build --wheel` plus wheel inspection
  - Result: built `nutmeg-0.2.0-py3-none-any.whl`; source notice, afternoon odds source, revision odds source, and scheduled registry sample all included, missing list `[]`.

## Spec Verification Checklist

- [x] R01: `zucai-odds-sync` local file CLI exists — verified by CLI odds sync test.
- [x] R02: Issue id, captured timestamp, source metadata, and 14 odds rows are parsed — verified by `test_odds_parser_extracts_14_rows_and_metadata`.
- [x] R03: Compatible odds snapshots are written — verified by snapshot writing and generated auto-run tests.
- [x] R04: Malformed/incomplete odds sources are rejected with warnings — verified by `test_odds_parser_warns_and_rejects_incomplete_snapshot`.
- [x] R05: Afternoon slot updates `odds_file` — verified by `test_odds_sync_writes_afternoon_snapshot_and_registry`.
- [x] R06: Revision slot updates `revision_odds_file` — verified by revision registry test.
- [x] R07: Existing issue/override fields are preserved — verified by registry preservation assertions.
- [x] R08: JSON CLI output exposes issue, slot, path, registry, rows, warnings — verified by CLI odds sync test.
- [x] R09: URL without live fetch is rejected — verified by service and CLI validation tests.
- [x] R10: Local-file use makes no default network calls — verified by local-only focused tests and URL rejection behavior.
- [x] R11: Documentation explains 16:00/18:30 odds flow — verified by `docs/architecture/zucai-odds-source.md` and README updates.
- [x] R12: Scope stays analysis-input only — verified by implementation boundaries and docs.
