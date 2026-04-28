# JCTZQ Mixed Parlay Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable竞彩足球 4-leg high-odds mixed-parlay report workflow with JSON/Markdown/PDF output and OpenClaw router support.

**Architecture:** Add focused `jczq` domain and service modules, wire a `jczq-mixed-report` CLI command, and expose the command through the existing safe OpenClaw router. Tests use injected/fake providers and local sample payloads; live calls remain opt-in at runtime.

**Tech Stack:** Python dataclasses, Typer CLI, httpx, reportlab, pytest, existing TelegramBotClient sender protocol.

---

### Task 1: Domain and Service Contracts

**Files:**
- Create: `nutmeg/domain/jczq.py`
- Create: `nutmeg/services/jczq.py`
- Test: `tests/test_jczq_service.py`

- [ ] Write failing tests for building two 4-leg report combinations from a fake Sporttery calculator payload.
- [ ] Verify RED with `uv run pytest tests/test_jczq_service.py -q`.
- [ ] Implement dataclasses, provider protocol, fake-friendly service, selection profiles, odds product calculation, and JSON contracts.
- [ ] Verify GREEN with `uv run pytest tests/test_jczq_service.py -q`.

### Task 2: Artifacts, PDF, and Dispatch

**Files:**
- Modify: `nutmeg/services/jczq.py`
- Test: `tests/test_jczq_service.py`

- [ ] Write failing tests for Markdown/PDF artifact generation and dry-run Telegram dispatch.
- [ ] Verify RED with `uv run pytest tests/test_jczq_service.py -q`.
- [ ] Implement Markdown rendering, Chinese-capable PDF rendering, JSON artifact writing, and dispatch status handling.
- [ ] Verify GREEN with `uv run pytest tests/test_jczq_service.py -q`.

### Task 3: CLI Command

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Test: `tests/test_cli.py`

- [ ] Write failing CLI test for `jczq-mixed-report --provider sample --pdf --format json` returning artifact paths and two combos.
- [ ] Verify RED with `uv run pytest tests/test_cli.py::test_jczq_mixed_report_command_generates_pdf_artifacts -q`.
- [ ] Add command options and service builder.
- [ ] Verify GREEN with the focused CLI test.

### Task 4: OpenClaw Router

**Files:**
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Test: `tests/test_openclaw_router.py`

- [ ] Write failing router tests for `jczq-mixed-report` command construction and dispatch confirmation.
- [ ] Verify RED with `uv run pytest tests/test_openclaw_router.py::test_router_builds_jczq_mixed_report_command_and_requires_dispatch_confirmation -q`.
- [ ] Add action parsing, validation, command builder, and confirmation gate.
- [ ] Verify GREEN with focused router tests.

### Task 5: Docs, Registry, and Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/integrations/openclaw-telegram-command-manual.md`
- Modify: `docs/integrations/openclaw-nutmeg-agent-instruction.md`
- Modify: `feature-list.json`
- Modify: `agent-progress.md`
- Modify: `memory/2026-04-26.md`

- [ ] Document CLI and bot usage.
- [ ] Add feature registry entry.
- [ ] Run `uv run ruff check .`.
- [ ] Run `python3 -m compileall nutmeg scripts/openclaw`.
- [ ] Run focused test suite and `bash scripts/verify.sh`.
- [ ] Refresh graph with `make graph` if code graph changed.
