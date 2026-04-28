# Verification: Event Data Tactical Models v0

## 2026-04-26 - RED/GREEN Implementation

- RED evidence: initial targeted test run failed on missing `nutmeg.domain.event_data`; after adding the first implementation, targeted tests exposed incorrect event-type normalization and missing pass-recipient metadata, proving the tests constrained the behavior.
- GREEN evidence: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_event_data.py tests/test_cli.py::test_event_tactical_models_command_is_registered_in_help tests/test_cli.py::test_event_tactical_models_command_returns_json_contract tests/test_cli.py::test_event_tactical_models_command_returns_unavailable_json -q` -> 13 passed.
- Lint evidence: `uv run ruff check nutmeg/domain/event_data.py nutmeg/services/event_data.py nutmeg/interfaces/cli.py tests/test_event_data.py tests/test_cli.py` -> all checks passed.
- CLI sample smoke: `uv run nutmeg event-tactical-models --fixture-id epl-001 --format json` -> fixture `epl-001`, quality `complete`, 13 events, 6 pass-network edges, 8 xT-lite actions, 7 VAEP-lite players, 3 artifacts.
- Artifact smoke: `uv run nutmeg event-tactical-models --fixture-id epl-001 --output-dir /tmp/... --format json` wrote `epl-001-pass-network.svg`, `epl-001-xt-heatmap.svg`, and `epl-001-contribution-bars.svg`.
- Package-data evidence: `uv build --wheel --out-dir /tmp/...` plus wheel inspection confirmed `nutmeg/event_data/samples/epl-001-events.json` is included.

## 2026-04-26 - Completion Gate

- Focused verification: event-data targeted suite -> 13 passed.
- Lint evidence: `uv run ruff check .` -> all checks passed.
- Compile evidence: `python3 -m compileall nutmeg` -> completed successfully.
- Full verification: `bash scripts/verify.sh` -> 244 passed.
- Graph refresh: `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` -> 84 modules / 134 edges.
