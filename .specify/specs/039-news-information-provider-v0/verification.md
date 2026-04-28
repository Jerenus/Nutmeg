# Verification: News Information Provider v0

Date: 2026-04-26  
Feature: `.specify/specs/039-news-information-provider-v0`

## RED Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_web.py::test_client_web_match_page_renders_information_items_and_reliability -q`
  - Result: failed before template implementation.
  - Expected failure: `assert 'Rumor of winger fitness test' in response.text`.
  - Root cause: Web match workspace rendered only `workspace.information.summary`, not item titles, source names, reliability labels, or warnings.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_service.py::test_client_service_match_workspace_reports_information_unavailable -q`
  - Result: failed before unavailable-payload implementation.
  - Expected failure: `KeyError: 'status'`.
  - Root cause: the no-provider information path returned a generic method-unavailable payload without status, items, or warnings.

## GREEN / Focused Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_web.py::test_client_web_match_page_renders_information_items_and_reliability -q`
  - Result: `1 passed`.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_service.py::test_client_service_match_workspace_reports_information_unavailable -q`
  - Result: `1 passed`.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_information_service.py tests/test_client_service.py::test_client_service_match_workspace_consumes_information_digest_payload tests/test_client_service.py::test_client_service_match_workspace_reports_information_unavailable tests/test_client_web.py::test_client_web_match_page_renders_information_items_and_reliability tests/test_cli.py::test_fixture_information_command_is_registered_in_help tests/test_cli.py::test_fixture_information_command_returns_json_contract tests/test_cli.py::test_fixture_information_command_returns_unavailable_json -q`
  - Result: `12 passed`.

## CLI / Packaging Evidence

- `uv run nutmeg fixture-information --fixture-id epl-001 --home-team Arsenal --away-team "Tottenham Hotspur" --format json`
  - Result: exit 0, `status=complete`, 3 deduplicated items, `source_count=3`, reliability labels `rumor`, `official`, and `credible`, plus rumor/unverified warning.
- Wheel package-data check:
  - Result: `nutmeg-0.2.0-py3-none-any.whl`, `missing=` for `nutmeg/information/samples/epl-001-information.json`.

## Full Verification Evidence

- `uv run ruff check .`
  - Result: `All checks passed!`
- `python3 -m compileall nutmeg`
  - Result: exit 0; compiled/listed Nutmeg packages including `nutmeg/information`.
- `bash scripts/verify.sh`
  - Result: `256 passed in 3.36s`.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out`
  - Result: graph refreshed to 87 modules / 136 internal dependency edges.

## Spec Verification Checklist

- [x] R01: Local JSON/RSS files normalize source name, title, summary, URL, publication/retrieval time, reliability, fixture ids, teams, and tags — verified by `tests/test_information_service.py::test_fixture_information_service_normalizes_json_reliability` and `tests/test_information_service.py::test_fixture_information_service_parses_local_rss_items`.
- [x] R02: Duplicate URL or title/source items collapse to one newest representative — verified by `tests/test_information_service.py::test_fixture_information_service_deduplicates_by_url_and_title_source`.
- [x] R03: Missing, empty, or malformed files return unavailable/partial state without fabricated updates — verified by `tests/test_information_service.py::test_fixture_information_service_unavailable_for_bad_sources` and `tests/test_cli.py::test_fixture_information_command_returns_unavailable_json`.
- [x] R04: Digest filters by fixture id and team names — verified by `tests/test_information_service.py::test_fixture_information_service_normalizes_json_reliability`.
- [x] R05: Rumor/unverified items are labeled and not treated as confirmed facts — verified by `tests/test_information_service.py::test_fixture_information_service_normalizes_json_reliability`, `tests/test_client_web.py::test_client_web_match_page_renders_information_items_and_reliability`, and `tests/test_client_service.py::test_client_service_match_workspace_consumes_information_digest_payload`.
- [x] R06: Client match workspace consumes a real information digest payload — verified by `tests/test_client_service.py::test_client_service_match_workspace_consumes_information_digest_payload` and `tests/test_client_web.py::test_client_web_match_page_renders_information_items_and_reliability`.
- [x] R07: Client workspace renders unavailable information truthfully when no source is configured — verified by `tests/test_client_service.py::test_client_service_match_workspace_reports_information_unavailable`.
- [x] R08: CLI JSON includes status, summary, items, source count, latest timestamp, and warnings — verified by `tests/test_cli.py::test_fixture_information_command_returns_json_contract`.
- [x] R09: CLI unavailable reports remain parseable and successful — verified by `tests/test_cli.py::test_fixture_information_command_returns_unavailable_json`.
- [x] R10: v0 remains no-network and no-scraping — verified by local file provider implementation, focused service tests, and no network source code in `nutmeg/services/information.py`.
- [x] R11: Documentation explains reliability labels and future live provider path — verified by `docs/architecture/information-provider.md`, `docs/architecture/ai-native-client.md`, `docs/architecture/design-gap-audit.md`, and README updates.
- [x] R12: Existing full verification continues to pass — verified by `bash scripts/verify.sh` (`256 passed`).
