# Verification: JCZQ Mixed Parlay Report v0

Date: 2026-04-26

## Evidence

- RED service test failed on missing `nutmeg.services.jczq`.
- GREEN focused service tests: `uv run pytest tests/test_jczq_service.py -q` -> 2 passed.
- RED CLI test failed before `jczq-mixed-report` command existed.
- GREEN CLI/router focused suite: `uv run pytest tests/test_jczq_service.py tests/test_cli.py::test_jczq_mixed_report_command_generates_pdf_artifacts tests/test_openclaw_router.py::test_router_builds_jczq_mixed_report_command_and_requires_dispatch_confirmation -q` -> 4 passed.
- Sample CLI smoke: `uv run nutmeg jczq-mixed-report --provider sample --output-dir .nutmeg-data/jczq-smoke --pdf --format json` -> 2 combinations, PDF starts with `%PDF`.
- Live CLI smoke: `uv run nutmeg jczq-mixed-report --provider live --output-dir .nutmeg-data/jczq-live-smoke --pdf --format json` -> official update `2026-04-26 18:51:44`, 2 combinations, PDF starts with `%PDF`.
- OpenClaw router print smoke: `python3 scripts/openclaw/nutmeg_command_router.py --print-command jczq-mixed-report --provider sample --pdf` -> allowlisted command envelope.
- OpenClaw router execute smoke: `python3 scripts/openclaw/nutmeg_command_router.py jczq-mixed-report --provider sample --pdf` -> ok true, 2 combinations, PDF artifact path returned.
- `uv run ruff check .` -> pass.
- `python3 -m compileall nutmeg scripts/openclaw` -> pass.
- `bash scripts/verify.sh` -> 327 passed.
- `make graph` -> 101 modules / 154 edges.

## Note

Full verification initially exposed an existing `OPENCLAW_CLI=1` handling bug in `default_openclaw_command()`. Root cause was an environment value intended as a boolean flag being treated as an executable path. The existing regression test was made green by ignoring boolean-like values (`1`, `true`, `yes`, `on`) when resolving the OpenClaw CLI command.
