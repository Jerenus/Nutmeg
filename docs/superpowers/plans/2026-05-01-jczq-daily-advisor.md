# JCZQ Daily Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily, dynamic竞彩足球 advisor that scans each day's sellable mixed-pool matches, generates stable explainable main/high-odds/contrarian inspiration plans, sends the report through Nutmeg bot at noon, and supports bot-driven revisions from the saved daily context.

**Architecture:** Add a focused `jczq_daily` domain/service layer that consumes the existing Sporttery calculator provider and never hard-codes match numbers. CLI, OpenClaw router, Telegram BotAdapter, and launchd scheduling all call the same service so scheduled reports and interactive revisions share context and output contracts.

**Tech Stack:** Python 3.12, Typer CLI, httpx-backed Sporttery provider, existing TelegramBotClient, pytest, ruff, launchd templates.

---

## File Structure

- Create `nutmeg/domain/jczq_daily.py`: serializable dataclasses for match snapshots, candidate picks, generated plans, report context, and revision metadata.
- Create `nutmeg/services/jczq_daily.py`: dynamic odds scanning, candidate scoring, combination construction, report rendering, artifact writing, Telegram dispatch, and saved-context revision.
- Modify `nutmeg/interfaces/cli.py`: add `jczq-daily-advisor` command and service builder using existing Telegram settings.
- Modify `nutmeg/interfaces/bot/adapter.py`: parse `/jczq`, `/jczq final`, and `/jczq revise <text>` and call an injectable daily-advisor workflow.
- Modify `scripts/openclaw/nutmeg_command_router.py`: allowlisted `jczq-daily-advisor` action with dispatch confirmation gate.
- Create `scripts/launchd/com.nutmeg.jczq.daily-noon.plist`: scheduled 12:00 Asia/Shanghai local run.
- Create `docs/architecture/jczq-daily-advisor.md`: usage, bot commands, schedule install notes, and risk boundary.
- Add tests in `tests/test_jczq_daily_service.py`, `tests/test_cli.py`, `tests/test_bot_adapter.py`, and `tests/test_openclaw_router.py`.

## Tasks

### Task 1: Domain and service RED/GREEN

- [ ] Write failing tests in `tests/test_jczq_daily_service.py` using a fake provider with two to five sellable matches; assert no hard-coded match numbers, plans use HAD/HHAD/TTG/CRS/HAFU pools, total odds are multiplied, and context artifacts are written.
- [ ] Run focused tests and verify they fail due to missing `nutmeg.domain.jczq_daily` / `nutmeg.services.jczq_daily`.
- [ ] Implement dataclasses and minimal dynamic service to pass tests.
- [ ] Run focused tests and keep them green.

### Task 2: Revision workflow RED/GREEN

- [ ] Add failing tests that save a context, call `revise(..., instruction="不要比分，提高到100倍")`, and assert a new revision version is recorded, score constraints change candidate selection, and rendered text mentions the instruction.
- [ ] Run focused tests and verify expected missing behavior.
- [ ] Implement saved-context loading and rule-based instruction parsing for stable revisions.
- [ ] Run focused tests and keep them green.

### Task 3: CLI and dispatch RED/GREEN

- [ ] Add failing CLI tests for `jczq-daily-advisor --provider sample --date 2026-05-01 --format json`, `--revision-text`, and dry-run Telegram dispatch.
- [ ] Run focused CLI tests and verify command missing.
- [ ] Wire CLI command and JSON/text payloads.
- [ ] Run focused CLI tests and keep them green.

### Task 4: Bot and OpenClaw RED/GREEN

- [ ] Add failing BotAdapter tests for `/jczq`, `/jczq final`, `/jczq revise 规避大众盘口` using a fake daily workflow.
- [ ] Add failing router test for `jczq-daily-advisor --dispatch-telegram --confirm-dispatch`.
- [ ] Implement parser/adapter/router changes.
- [ ] Run focused bot/router tests and keep them green.

### Task 5: Schedule, docs, verification

- [ ] Add launchd template for noon local execution and test that it contains `Hour 12`, `Minute 0`, `jczq-daily-advisor`, and `--dispatch-telegram --no-dry-run`.
- [ ] Update docs and README command references.
- [ ] Run ruff, compileall, focused pytest, and broad `scripts/verify.sh` if time permits.

## Self-Review

- Dynamic daily adaptation: covered by service tests with fake current-day matches and no hard-coded match ids.
- Multi-pool high-odds inspiration: covered by candidate generation over HAD/HHAD/TTG/CRS/HAFU and plan assertions.
- Bot revision loop: covered by BotAdapter and service revision tests.
- Scheduled noon send: covered by launchd template and CLI dispatch command.
- Safety boundary: docs and rendered report state analysis only, no wager execution or guaranteed profit.
