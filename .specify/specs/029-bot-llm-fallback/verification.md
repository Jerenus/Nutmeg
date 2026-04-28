# Verification: Bot LLM Fallback

**Date**: 2026-04-25  
**Status**: PASS for implementation and local contracts; live OpenAI smoke blocked by API auth 401.

## Commands

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_llm_provider.py tests/test_bot_adapter.py tests/test_cli.py -q` -> 54 passed
- `uv run ruff check nutmeg/agents/llm_provider.py nutmeg/config/settings.py nutmeg/interfaces/bot/adapter.py nutmeg/interfaces/cli.py tests/test_llm_provider.py tests/test_bot_adapter.py tests/test_cli.py` -> pass
- `uv run nutmeg bot-dry-run --message '/start' --format json` -> help payload returned with `/brief` and `telegram-bot-run` guidance
- `uv run nutmeg telegram-bot-status --format json` -> fallback fields present; after local `.env` switch, enabled/configured/model reports true/true/gpt-5.5
- `uv run nutmeg bot-dry-run --message '今天有哪些热门比赛？请简单告诉我怎么用Nutmeg查看。' --format json` -> fallback path executed but live OpenAI returned 401; no secrets leaked
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` -> pass
- `uv run ruff check .` -> pass
- `python3 -m compileall nutmeg` -> pass
- `bash scripts/verify.sh` -> 151 passed

## Spec Verification Checklist

- [x] US1 natural-language fallback response — verified by `tests/test_bot_adapter.py::test_bot_adapter_uses_fallback_for_unsupported_natural_language`
- [x] US2 safe OpenAI Responses provider — verified by `tests/test_llm_provider.py::test_openai_bot_fallback_provider_posts_responses_payload`
- [x] US3 CLI/Telegram wiring — verified by `tests/test_cli.py::test_bot_dry_run_command_uses_llm_fallback_for_plain_message` plus `build_telegram_bot_runner` wiring inspection
- [x] US4 deterministic `/start` help — verified by `tests/test_bot_adapter.py::test_bot_adapter_start_returns_deterministic_help_without_fallback` and local smoke
- [x] FR-001 default-off key-gated builder — verified by `tests/test_llm_provider.py::test_bot_fallback_provider_builder_is_default_off_without_flag_or_key`
- [x] FR-002 configurable default `gpt-5.5` model — verified by settings defaults and provider payload test
- [x] FR-003 direct HTTPX `/responses` usage — verified by `tests/test_llm_provider.py::test_openai_bot_fallback_provider_posts_responses_payload`
- [x] FR-004 no key/token leakage — verified by CLI/provider tests and live smoke preview checks
- [x] FR-005 deterministic `/brief` remains primary — verified by existing bot adapter and CLI tests continuing to pass
- [x] FR-006 fallback on unsupported/failed paths or deterministic help when absent — verified by adapter tests
