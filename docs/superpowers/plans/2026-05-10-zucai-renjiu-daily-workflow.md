# Zucai Renjiu Daily Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable daily 任选9 workflow that produces conservative/main/aggressive tickets, artifacts, and natural-language bot triggering.

**Architecture:** Add a focused `zucai_renjiu` domain and `zucai_renjiu_daily` service that consume existing Zucai issue/odds snapshots and reuse the existing Telegram/PDF patterns. Expose the service through a new CLI command and inject it into `BotAdapter` through a small workflow wrapper so CLI and natural-language triggers share implementation.

**Tech Stack:** Python 3.12, Typer CLI, dataclasses, reportlab PDF rendering, pytest, existing `TelegramBotClient` seam.

---

### Task 1: Domain and Ticket Generation Core

**Files:**
- Create: `nutmeg/domain/zucai_renjiu.py`
- Create: `nutmeg/services/zucai_renjiu_daily.py`
- Test: `tests/test_zucai_renjiu_daily.py`

- [ ] **Step 1: Write failing tests for three budget tiers**

Add tests that build a sample 14-match issue and odds snapshot, run the service with dry-run dispatch, and assert it returns exactly three tickets named conservative/main/aggressive with costs in the requested bands.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_zucai_renjiu_daily.py::test_renjiu_daily_generates_three_budget_tiers -q`
Expected: FAIL with missing module `nutmeg.services.zucai_renjiu_daily`.

- [ ] **Step 3: Implement minimal domain dataclasses and service**

Create immutable dataclasses for match analysis, ticket, artifacts, dispatch, and report. Implement deterministic ticket generation from odds-based uncertainty scoring and budget targets.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_zucai_renjiu_daily.py::test_renjiu_daily_generates_three_budget_tiers -q`
Expected: PASS.

### Task 2: Artifacts and PDF Rendering

**Files:**
- Modify: `nutmeg/services/zucai_renjiu_daily.py`
- Test: `tests/test_zucai_renjiu_daily.py`

- [ ] **Step 1: Write failing tests for Markdown/JSON/PDF artifacts**

Assert `analysis.md`, `analysis.json`, and `analysis.pdf` are written under `daily/<date>/renjiu/`, PDF starts with `%PDF`, and markdown includes the three ticket names.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_zucai_renjiu_daily.py::test_renjiu_daily_writes_artifacts_and_pdf -q`
Expected: FAIL because artifact rendering is incomplete.

- [ ] **Step 3: Implement Markdown, JSON, and reportlab PDF rendering**

Reuse the existing STSong-Light font pattern and simple tables from `zucai.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_zucai_renjiu_daily.py::test_renjiu_daily_writes_artifacts_and_pdf -q`
Expected: PASS.

### Task 3: CLI Command

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Add a CLI runner test that invokes `zucai-renjiu-daily --date 2026-05-10 --issue-file <sample> --odds-file <sample> --output-dir <tmp> --format json` and asserts JSON contains `recommended_ticket_id` and three tickets.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_zucai_renjiu_daily_command_generates_three_tiers -q`
Expected: FAIL because the command does not exist.

- [ ] **Step 3: Add CLI builder and command**

Wire a new `build_zucai_renjiu_daily_service()` and Typer command using existing option style.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_zucai_renjiu_daily_command_generates_three_tiers -q`
Expected: PASS.

### Task 4: Natural-Language Bot Trigger

**Files:**
- Modify: `nutmeg/interfaces/bot/adapter.py`
- Modify: `nutmeg/interfaces/cli.py`
- Test: `tests/test_telegram_bot.py`

- [ ] **Step 1: Write failing bot parser/adapter tests**

Add tests for `今天任九方案`, `做今天的14选9`, and `today's renjiu plan` that assert the adapter invokes a Renjiu workflow and returns the recommended ticket text.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram_bot.py::test_bot_handles_renjiu_natural_language -q`
Expected: FAIL because no Renjiu trigger exists.

- [ ] **Step 3: Implement trigger parser and workflow injection**

Add a `renjiu_workflow` dependency to `BotAdapter`, parse Renjiu trigger phrases before fallback, and wire the production bot runner to the CLI-created workflow.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_telegram_bot.py::test_bot_handles_renjiu_natural_language -q`
Expected: PASS.

### Task 5: Final Verification

**Files:**
- All touched files.

- [ ] **Step 1: Run focused tests**

Run: `uv run pytest tests/test_zucai_renjiu_daily.py tests/test_cli.py::test_zucai_renjiu_daily_command_generates_three_tiers tests/test_telegram_bot.py::test_bot_handles_renjiu_natural_language -q`
Expected: PASS.

- [ ] **Step 2: Run a real dry-run smoke**

Run: `uv run nutmeg zucai-renjiu-daily --date today --issue-file .nutmeg-data/zucai/26074-issue.json --odds-file .nutmeg-data/zucai/26074-odds-jczq-1258.json --output-dir .nutmeg-data/zucai --dispatch-telegram --dry-run --format json`
Expected: JSON with three tickets, artifacts under `.nutmeg-data/zucai/daily/2026-05-10/renjiu/`, and dispatch status `dry_run`.

- [ ] **Step 3: Summarize delivery**

Report files changed, tests run, smoke output path, and how to trigger naturally.

## Self-Review

- Spec coverage: Natural-language trigger, three tiers, artifacts, dispatch, fail-loud data gaps, and tests are covered.
- Placeholder scan: No unresolved placeholders are present.
- Type consistency: Plan consistently uses `ZucaiRenjiuDailyService`, `zucai-renjiu-daily`, and three ticket IDs `conservative`, `main`, `aggressive`.
