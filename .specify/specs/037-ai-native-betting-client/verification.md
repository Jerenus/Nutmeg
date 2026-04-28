# Verification: AI-Native Betting Client

## 2026-04-26 - Phase 1/2 + US1

- RED evidence: Phase 2 targeted tests initially failed on missing `nutmeg.domain.client` and `nutmeg.interfaces.client_web`; US1 targeted tests initially failed on missing `daily_feed`, feed API/page routes, and CLI payload.
- GREEN evidence: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_domain.py tests/test_client_state_repository.py tests/test_client_service.py tests/test_client_web.py tests/test_cli.py::test_client_commands_are_registered_in_help tests/test_cli.py::test_client_status_command_returns_json_contract tests/test_cli.py::test_client_feed_command_returns_json_contract -q` -> 20 passed.
- Lint evidence: `uv run ruff check nutmeg/domain/client.py nutmeg/storage/client_state_repository.py nutmeg/services/client.py nutmeg/interfaces/client_web.py nutmeg/interfaces/cli.py tests/test_client_domain.py tests/test_client_state_repository.py tests/test_client_service.py tests/test_client_web.py tests/test_cli.py` -> all checks passed.
- Full verification: `bash scripts/verify.sh` -> 204 passed.
## 2026-04-26 - US2 Match Workspace

- RED evidence: US2 targeted tests initially failed on unsupported match workspace provider injection, missing audit redaction, missing `/client/api/matches/{fixture_id}` and `/client/matches/{fixture_id}` routes, and stubbed `client-match` CLI output.
- GREEN evidence: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_service.py::test_client_service_match_workspace_combines_analysis_sections_and_audit tests/test_client_service.py::test_client_service_match_workspace_conflict_lowers_actionability tests/test_client_service.py::test_client_service_match_workspace_evidence_has_source_and_timestamps tests/test_client_state_repository.py::test_client_state_repository_audit_records_do_not_store_secret_keys tests/test_client_web.py::test_client_web_match_api_returns_contract_payload tests/test_client_web.py::test_client_web_match_page_renders_workspace_sections tests/test_cli.py::test_client_match_command_returns_json_contract -q` -> 7 passed.
- Focused client verification: client domain/state/service/web plus client CLI contract tests -> 27 passed.
- Full verification: `bash scripts/verify.sh` -> 211 passed.
## 2026-04-26 - US3 Grounded Follow-Up

- RED evidence: US3 targeted tests initially failed on missing `ClientService.answer_question()`, missing question POST endpoint, missing question form, and stubbed `client-question` CLI payload.
- GREEN evidence: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_service.py::test_client_service_grounded_follow_up_uses_workspace_evidence tests/test_client_service.py::test_client_service_follow_up_refuses_out_of_scope_or_unsupported_requests tests/test_client_service.py::test_client_service_follow_up_deterministic_verdict_overrides_generated_wording tests/test_client_web.py::test_client_web_match_question_endpoint_returns_grounded_answer tests/test_client_web.py::test_client_web_match_page_renders_question_form tests/test_cli.py::test_client_question_command_returns_json_contract -q` -> 6 passed.
- Focused client verification: client domain/state/service/web plus client CLI contract tests -> 33 passed.
- Full verification: `bash scripts/verify.sh` -> 217 passed.
## 2026-04-26 - US4 Subscription Readiness

- RED evidence: US4 targeted tests initially failed on missing workspace entitlement payload, missing premium gating, and missing gated web copy.
- GREEN evidence: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_state_repository.py::test_client_state_repository_entitlement_owner_fallback_and_expiration tests/test_client_service.py::test_client_service_gates_premium_workspace_without_leaking_value_facts tests/test_client_service.py::test_client_service_user_state_isolation_for_status_watchlist_alerts_and_audits tests/test_client_web.py::test_client_web_match_page_renders_gated_premium_message tests/test_cli.py::test_client_status_command_returns_entitlement_for_requested_user -q` -> 5 passed.
- Focused client verification: client domain/state/service/web plus client CLI contract tests -> 38 passed.
- Full verification: `bash scripts/verify.sh` -> 222 passed.
## 2026-04-26 - US5 Alerts and Calibration

- RED evidence: US5 targeted tests first failed on missing material-alert, prediction-recording, watchlist/alerts/prediction HTTP routes, and client watchlist/alerts/prediction CLI commands; later UI/calibration tests failed on missing watchlist controls, grouped alert snippets, prediction form, and calibration review payload.
- GREEN evidence: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_state_repository.py::test_client_state_repository_watchlist_duplicate_updates_preferences tests/test_client_service.py::test_client_service_creates_material_change_alerts_for_supported_change_types tests/test_client_service.py::test_client_service_groups_repeated_alerts_by_group_key tests/test_client_service.py::test_client_service_records_prediction_with_audit_context tests/test_client_web.py::test_client_web_watchlist_alerts_and_prediction_contracts tests/test_client_web.py::test_client_web_feed_page_renders_watchlist_controls tests/test_client_web.py::test_client_web_match_page_renders_prediction_controls tests/test_client_web.py::test_client_web_feed_page_renders_grouped_alert_snippets tests/test_cli.py::test_client_watchlist_alert_and_prediction_commands_return_json -q` -> 9 passed.
- Focused client verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_client_domain.py tests/test_client_state_repository.py tests/test_client_service.py tests/test_client_web.py tests/test_cli.py::test_client_commands_are_registered_in_help tests/test_cli.py::test_client_status_command_returns_json_contract tests/test_cli.py::test_client_feed_command_returns_json_contract tests/test_cli.py::test_client_match_command_returns_json_contract tests/test_cli.py::test_client_question_command_returns_json_contract tests/test_cli.py::test_client_status_command_returns_entitlement_for_requested_user tests/test_cli.py::test_client_watchlist_alert_and_prediction_commands_return_json` -> 47 passed.
- Package-data evidence: `uv build --wheel --out-dir /tmp/...` plus wheel inspection confirmed `feed.html`, `match.html`, `app.css`, and `app.js` are included.

## 2026-04-26 - Final Polish and Completion Gate

- Lint evidence: `uv run ruff check .` -> all checks passed.
- Compile evidence: `python3 -m compileall nutmeg` -> completed successfully.
- Full verification: `bash scripts/verify.sh` -> 231 passed.
- Graph refresh: `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out` -> 81 modules / 132 edges.
