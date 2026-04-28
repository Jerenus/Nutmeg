# Verification: Content Publisher v0

Feature: `.specify/specs/045-content-publisher-v0`
Status: Verified on 2026-04-26.

## RED Evidence

- `uv run pytest tests/test_content_service.py tests/test_cli.py::test_content_pack_command_generates_json_artifacts tests/test_cli.py::test_content_pack_command_rejects_missing_report -q`
  - Initial result: `9 failed`.
  - Expected failures: `ModuleNotFoundError: No module named 'nutmeg.services.content'` and missing `content-pack` command before implementation.

## GREEN Focused Evidence

- `uv run pytest tests/test_content_service.py tests/test_cli.py::test_content_pack_command_generates_json_artifacts tests/test_cli.py::test_content_pack_command_rejects_missing_report -q`
  - Result after implementation: `9 passed`.
- `uv run ruff check nutmeg/services/content.py nutmeg/domain/content.py nutmeg/interfaces/cli.py tests/test_content_service.py tests/test_cli.py`
  - Result: `All checks passed!`

## CLI Smoke Evidence

- Deterministic no-network smoke:
  - Command: `uv run nutmeg content-pack --report-file nutmeg/content/samples/26068-content-report.json --limit 1 --output-dir .nutmeg-data/content-smoke --llm-mode deterministic --format json`
  - Result: one pack for `都灵 vs 国际米兰`, 5 titles, `risk=MEDIUM`, `publish_recommendation=review`, JSON/Markdown artifacts written under `.nutmeg-data/content-smoke/`.
- OpenClaw LLM smoke:
  - Command: `uv run nutmeg content-pack --report-file nutmeg/content/samples/26068-content-report.json --limit 1 --output-dir .nutmeg-data/content-openclaw-smoke --llm-mode openclaw --openclaw-model nyu-openai-chat/gpt-5.5 --format json`
  - Result: `llm=openclaw:nyu-openai-chat/gpt-5.5`, `llm_status=generated`, one pack for `都灵 vs 国际米兰`, 5 titles, `risk=MEDIUM`, `publish_recommendation=review`, warnings `0`, JSON/Markdown artifacts written under `.nutmeg-data/content-openclaw-smoke/`.

## Full Verification Evidence

- `uv run ruff check .`
  - Result: `All checks passed!`
- `python3 -m compileall nutmeg scripts/openclaw`
  - Result: completed successfully and compiled the new `nutmeg/content/__init__.py` path.
- `bash scripts/verify.sh`
  - Result: `319 passed in 4.09s`.
- `uv build --wheel` plus wheel inspection
  - Result: `Successfully built dist/nutmeg-0.2.0-py3-none-any.whl`; `nutmeg/content/samples/26068-content-report.json` is included in the wheel.
- `python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out`
  - Result: graph refreshed to `99 modules, 152 edges`.

## Acceptance Notes

- The module remains artifact-only in v0: JSON and Markdown review packs are written, but no external platform publishing is performed.
- Live LLM generation goes through OpenClaw's `infer model run` interface; tests use fake/deterministic providers and make no live LLM calls.
- Compliance is deterministic after generation and maps `LOW -> publish`, `MEDIUM -> review`, `HIGH/BLOCKED -> skip`.

## Bot Runtime Follow-up Evidence

Status: Verified on 2026-04-26 after syncing `/content` into `nutmegbot`.

- Root cause found for Bot-only fallback: the OpenClaw agent exec environment exposes `OPENCLAW_CLI=1`; earlier content-provider resolution treated that boolean-like value as the executable path and attempted to run `1`.
- Added regression coverage:
  - `uv run pytest tests/test_content_service.py::test_openclaw_content_provider_ignores_boolean_openclaw_cli_env -q`
  - RED result before fix: failed with actual command `1`.
  - GREEN result after fix: passed.
- Added diagnostics coverage:
  - `uv run pytest tests/test_content_service.py::test_openclaw_content_provider_reports_attempted_cli_path -q`
  - Result: passed; future CLI-not-found fallback warnings include the attempted path.
- Router smoke with Bot-like env:
  - Command: `OPENCLAW_CLI=1 python3 scripts/openclaw/nutmeg_command_router.py content --report-file nutmeg/content/samples/26068-content-report.json --limit 1 --llm-mode openclaw`
  - Result: `llm_status=generated`, no warnings.
- Nutmeg Bot smoke:
  - Command: `openclaw agent --agent nutmegbot --session-id nutmeg-content-bot-fixed-20260426-1 --message '/content nutmeg/content/samples/26068-content-report.json' --json`
  - Result: returned `LLM 状态：generated，未使用 fallback`; artifacts written to `.nutmeg-data/content/content-pack-26068-20260426T105446+0000.{json,md}`.
- Fresh regression verification:
  - `uv run pytest tests/test_content_service.py tests/test_openclaw_router.py -q` -> `19 passed`.
  - `uv run ruff check .` -> `All checks passed!`.
  - `python3 -m compileall nutmeg scripts/openclaw` -> completed successfully.
  - `bash scripts/verify.sh` -> `327 passed in 4.28s`.
