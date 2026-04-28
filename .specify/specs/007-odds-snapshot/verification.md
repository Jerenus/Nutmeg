# Verification: Odds Snapshot and Fair Probability

## Implementation Complete — Verification Evidence

**Fresh odds suite:** PASS via `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_api_football.py tests/test_the_odds_api.py tests/test_odds_event_repository.py tests/test_odds_history_repository.py tests/test_odds_service.py tests/test_cli.py -q`  
**Focused reconciliation suite:** PASS via `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_the_odds_api.py tests/test_odds_event_repository.py tests/test_odds_service.py -q`  
**Lint:** PASS via `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/ruff check .`  
**Compile:** PASS via `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m compileall nutmeg`

## Spec Verification Checklist

- [x] R01: Build an odds snapshot only for a cached fixture — verified by `tests/test_odds_service.py::test_odds_snapshot_service_builds_fair_probabilities_and_marks_incomplete_market` and `tests/test_odds_service.py::test_odds_snapshot_service_raises_for_unknown_fixture`
- [x] R02: Expose source/update/bookmaker metadata — verified by `tests/test_api_football.py::test_fetch_fixture_odds_normalizes_supported_markets_and_deduplicates_quotes`
- [x] R03: Normalize stable supported markets — verified by `tests/test_api_football.py::test_fetch_fixture_odds_normalizes_supported_markets_and_deduplicates_quotes` and `tests/test_api_football.py::test_fetch_fixture_odds_accepts_supported_market_id_even_if_name_varies`
- [x] R04: Preserve available quotes and explicit incomplete/unavailable markets — verified by `tests/test_odds_service.py::test_odds_snapshot_service_builds_fair_probabilities_and_marks_incomplete_market` and `tests/test_odds_service.py::test_odds_snapshot_service_marks_missing_provider_markets_as_unavailable`
- [x] R05: Derive no-vig fair probabilities and fair odds for complete markets — verified by `tests/test_betting.py::test_no_vig_probabilities_sum_to_one`, `tests/test_betting.py::test_fair_odds_inverts_probability`, and `tests/test_odds_service.py::test_odds_snapshot_service_builds_fair_probabilities_and_marks_incomplete_market`
- [x] R06: Expose consensus fair probability, average price, best price, and coverage counts — verified by `tests/test_odds_service.py::test_odds_snapshot_service_builds_fair_probabilities_and_marks_incomplete_market`
- [x] R07: Render odds snapshot in text and JSON CLI forms — verified by `tests/test_cli.py::test_odds_snapshot_command_returns_json` and `tests/test_cli.py::test_odds_snapshot_command_renders_text`
- [x] R08: Fail cleanly for unknown fixture or missing provider config, while staying truthful when odds are unavailable — verified by `tests/test_cli.py::test_odds_snapshot_command_fails_cleanly_for_missing_fixture`, `tests/test_cli.py::test_odds_snapshot_command_fails_cleanly_without_api_key`, and `tests/test_odds_service.py::test_odds_snapshot_service_marks_missing_provider_markets_as_unavailable`
- [x] R09: Retain source attribution and separate raw bookmaker prices from derived fair probabilities — verified by `tests/test_cli.py::test_odds_snapshot_command_returns_json`
- [x] R10: Keep the provider boundary replaceable — verified by `tests/test_odds_service.py` provider-selection coverage plus `tests/test_the_odds_api.py` showing a real The Odds API adapter behind the same service contract
- [x] R11: Persist and expose historical market summaries with movement/drift signals — verified by `tests/test_odds_service.py::test_odds_snapshot_service_builds_history_movement_and_market_drift` and `tests/test_cli.py::test_odds_snapshot_command_renders_text`
- [x] R12: Cover normalization, duplicate handling, fair-probability derivation, CLI rendering, history rendering, provider selection, unavailable-provider behavior, and secondary-provider reconciliation with tests — verified by `tests/test_api_football.py`, `tests/test_the_odds_api.py`, `tests/test_odds_event_repository.py`, `tests/test_odds_service.py`, and `tests/test_cli.py`
- [x] R13: Update architecture and continuity artifacts — verified by `docs/architecture/odds-snapshot.md`, `agent-progress.md`, `.specify/specs/007-odds-snapshot/contracts/cli-odds-snapshot.md`, and `feature-list.json`
