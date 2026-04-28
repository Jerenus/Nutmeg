# OpenClaw Telegram Nutmeg Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an OpenClaw Telegram bot operate Nutmeg through a documented, constrained CLI bridge.

**Architecture:** Nutmeg remains the football-analysis backend. OpenClaw reads the integration manual and invokes `scripts/openclaw/nutmeg_command_router.py`, which validates intent-specific parameters and serializes `uv run nutmeg` calls behind a local lock.

**Tech Stack:** Python stdlib (`argparse`, `json`, `subprocess`, `fcntl` on POSIX), existing Nutmeg CLI, pytest, ruff.

---

### Task 1: Router Test Contract

**Files:**
- Create: `tests/test_openclaw_router.py`
- Create: `scripts/openclaw/nutmeg_command_router.py`

- [x] Write tests proving:
  - `popular` maps to `uv run nutmeg popular-matches --league epl --days 3 --limit 5 --format json`
  - unknown actions fail before shell execution
  - `sync` requires `--confirm-live`
  - `daily --dispatch-telegram` requires `--confirm-dispatch`
  - `player` preserves multi-word team/player names
  - command execution returns a JSON envelope

- [x] Run focused tests and verify RED before adding the router.

### Task 2: Safe Router Implementation

**Files:**
- Create: `scripts/openclaw/nutmeg_command_router.py`

- [x] Implement intent-specific parsers.
- [x] Validate league, days, limit, fixture id, season, team/player/query strings.
- [x] Emit JSON envelopes with `ok`, `action`, `command`, `returncode`, `payload`, `stdout`, and `stderr`.
- [x] Add `--print-command` mode for OpenClaw dry-runs.
- [x] Add a lock file under `.nutmeg-data/state/openclaw-router.lock`.

### Task 3: OpenClaw Documentation

**Files:**
- Create: `docs/integrations/openclaw-telegram-command-manual.md`
- Create: `docs/integrations/openclaw-nutmeg-agent-instruction.md`
- Create: `docs/integrations/openclaw-botfather-commands.txt`
- Modify: `README.md`

- [x] Document Telegram commands, natural-language routing, CLI commands,
  safety policy, response formatting, and operating modes.
- [x] Provide a short instruction file suitable for an OpenClaw Telegram agent.
- [x] Provide a BotFather `/setcommands` list.

### Task 4: Verification

**Files:**
- Modify: `agent-progress.md`
- Modify: `memory/2026-04-26.md`

- [x] Run focused router tests.
- [x] Run ruff on router/tests.
- [x] Run a router smoke command in print mode and demo execution mode.
- [x] Run `python3 -m compileall scripts/openclaw`.
- [x] Update progress and memory with decisions and usage.
