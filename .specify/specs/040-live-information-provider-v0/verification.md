# Verification: Live Information Provider v0

Date: 2026-04-26  
Feature: `.specify/specs/040-live-information-provider-v0`

## Baseline Evidence

- `bash scripts/verify.sh`
  - Result before implementation: `256 passed in 3.55s`.

## RED Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_information_service.py -q`
  - Result: collection failed before implementation.
  - Expected failure: `ImportError: cannot import name 'InformationCacheEntry'` and missing `InformationSourceDefinition`.
  - Root cause: 040 domain entities did not exist yet.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_cli.py::test_fixture_information_command_accepts_live_manifest_flags tests/test_cli.py::test_fixture_information_command_live_manifest_unavailable_json tests/test_cli.py::test_client_match_command_can_use_live_information_manifest tests/test_client_service.py::test_client_service_can_override_information_provider_for_manifest_digest -q`
  - Result: 4 failed.
  - Expected failures: missing `build_live_fixture_information_service` and missing `ClientService.set_information_provider()`.
  - Root cause: live manifest provider was not wired into CLI/client surfaces.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_information_service.py::test_live_information_source_defaults_do_not_retag_explicit_fixture -q`
  - Result: failed because an explicitly `epl-999` Liverpool item was retagged by source defaults and matched `epl-001`.
  - Root cause: source-level fixture/team hints were applied to every item rather than only items missing those tags.

## GREEN / Focused Evidence

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_information_service.py -q`
  - Result: `17 passed`.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_cli.py::test_fixture_information_command_accepts_live_manifest_flags tests/test_cli.py::test_fixture_information_command_live_manifest_unavailable_json tests/test_cli.py::test_client_match_command_can_use_live_information_manifest tests/test_client_service.py::test_client_service_can_override_information_provider_for_manifest_digest -q`
  - Result: `4 passed`.
- Focused 039/040 information/client/CLI/Web suite:
  - Command: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_information_service.py tests/test_cli.py::test_fixture_information_command_accepts_live_manifest_flags tests/test_cli.py::test_fixture_information_command_live_manifest_unavailable_json tests/test_cli.py::test_client_match_command_can_use_live_information_manifest tests/test_client_service.py::test_client_service_can_override_information_provider_for_manifest_digest tests/test_cli.py::test_fixture_information_command_returns_json_contract tests/test_cli.py::test_fixture_information_command_returns_unavailable_json tests/test_client_service.py::test_client_service_match_workspace_consumes_information_digest_payload tests/test_client_web.py::test_client_web_match_page_renders_information_items_and_reliability -q`
  - Result: `25 passed`.

## CLI / Packaging Evidence

- `uv run nutmeg fixture-information --fixture-id epl-001 --home-team Arsenal --away-team "Tottenham Hotspur" --sources-config nutmeg/information/samples/epl-001-sources.json --format json`
  - Result: exit 0, `status=complete`, 3 deduplicated items, `source_count=3`, and rumor/unverified warning.
  - Regression note: source defaults no longer retag the unrelated `epl-999` item.
- Wheel package-data check:
  - Result: `nutmeg-0.2.0-py3-none-any.whl`, `missing=` for both `nutmeg/information/samples/epl-001-information.json` and `nutmeg/information/samples/epl-001-sources.json`.

## Full Verification Evidence

- `uv run ruff check .`
  - Result: `All checks passed!`
- `python3 -m compileall nutmeg`
  - Result: exit 0; listed Nutmeg packages including `nutmeg/information/samples`.
- `bash scripts/verify.sh`
  - Result: `271 passed in 3.47s`.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out`
  - Result: graph refreshed to 87 modules / 136 internal dependency edges.

## Spec Verification Checklist

- [x] R01: Manifest supports local file sources and remote URL sources — verified by `tests/test_information_service.py::test_live_information_manifest_loads_defaults_and_warnings` and `tests/test_information_service.py::test_live_information_provider_loads_manifest_sources`.
- [x] R02: Source definitions include name, kind, enabled state, reliability, URL/path, tags, teams, fixture ids, and fetch policy — verified by `tests/test_information_service.py::test_information_source_definition_and_cache_entry_serialize`.
- [x] R03: Remote fetching is opt-in and default digest builds do not contact network — verified by `tests/test_information_service.py::test_live_information_provider_does_not_fetch_remote_without_live_flag`.
- [x] R04: Remote fetches enforce timeout and response-size limits — verified by `tests/test_information_service.py::test_live_information_provider_reports_remote_failures`.
- [x] R05: Remote responses cache with fetched timestamp, URL, content type, status, and body — verified by `tests/test_information_service.py::test_live_information_provider_fetches_remote_rss_and_writes_cache`.
- [x] R06: Fresh cache entries are usable without network access — verified by `tests/test_information_service.py::test_live_information_provider_uses_fresh_cache_without_fetch`.
- [x] R07: Stale cache fallback after live fetch failure is labeled partial/stale — verified by `tests/test_information_service.py::test_live_information_provider_uses_stale_cache_after_fetch_failure`.
- [x] R08: Remote failures create warnings/source health without fabricated items — verified by `tests/test_information_service.py::test_live_information_provider_reports_remote_failures`.
- [x] R09: Remote JSON and RSS/Atom normalize into existing information item/digest contracts — verified by `tests/test_information_service.py::test_live_information_provider_loads_manifest_sources` and `tests/test_information_service.py::test_live_information_provider_fetches_remote_rss_and_writes_cache`.
- [x] R10: Deduplication, fixture/team filtering, reliability labels, and rumor warnings apply across local/remote sources — verified by `tests/test_information_service.py::test_live_information_source_defaults_do_not_retag_explicit_fixture` and existing 039 information tests.
- [x] R11: `fixture-information` exposes manifest/cache/live/timeout/size controls with parseable JSON — verified by `tests/test_cli.py::test_fixture_information_command_accepts_live_manifest_flags` and `tests/test_cli.py::test_fixture_information_command_live_manifest_unavailable_json`.
- [x] R12: `client-match` can use an explicit information manifest without user-state changes — verified by `tests/test_cli.py::test_client_match_command_can_use_live_information_manifest` and `tests/test_client_service.py::test_client_service_can_override_information_provider_for_manifest_digest`.
- [x] R13: Docs explain no-scraping scope, opt-in live fetch, cache semantics, reliability, and future authenticated provider path — verified by `docs/architecture/information-provider.md`, README, `docs/architecture/ai-native-client.md`, and `docs/architecture/design-gap-audit.md`.
- [x] R14: Existing full verification continues to pass — verified by `bash scripts/verify.sh` (`271 passed`).
