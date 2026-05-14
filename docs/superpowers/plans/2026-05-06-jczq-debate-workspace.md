# JCZQ Debate Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a local daily JCZQ debate workspace where GPT, Claude, and the human operator can share one frozen brief, record independent analyses, compare disagreements, and finalize the day's betting plan.

**Architecture:** Add a focused `nutmeg/services/jczq_debate.py` service that owns file layout and Markdown/JSON artifacts under `.nutmeg-data/jczq/daily/YYYY-MM-DD/debate/`. Add CLI commands in `nutmeg/interfaces/cli.py` for `jczq-debate-init`, `jczq-debate-compare`, and `jczq-debate-finalize`. Keep Phase 1 local-first: no external model API calls and no automatic betting execution.

**Tech Stack:** Python 3.12, Typer CLI, pytest, existing JCZQ daily advisor report JSON/brief artifacts.

---

### Task 1: Debate Workspace Service

**Files:**
- Create: `nutmeg/services/jczq_debate.py`
- Test: `tests/test_jczq_debate_service.py`

- [ ] Write failing tests that `initialize_workspace()` creates `shared-brief.md`, `gpt-analysis.md`, `claude-analysis.md`, `human-notes.md`, and `decision-log.json` under the date's debate directory.
- [ ] Verify the test fails because `nutmeg.services.jczq_debate` does not exist.
- [ ] Implement `JczqDebateWorkspaceService.initialize_workspace()` using an existing brief if present, otherwise a supplied brief text.
- [ ] Re-run the focused test and verify it passes.

### Task 2: Compare And Finalize

**Files:**
- Modify: `nutmeg/services/jczq_debate.py`
- Test: `tests/test_jczq_debate_service.py`

- [ ] Write failing tests that `compare_workspace()` extracts ticket lines from GPT/Claude analyses and writes `disagreements.md` plus JSON consensus/conflict lists.
- [ ] Write failing tests that `finalize_workspace()` writes `final-plan.md` and `final-plan.json` from human notes plus selected analysis text.
- [ ] Implement a deterministic Markdown parser for ticket bullets and dropped-leg markers; keep it simple and transparent for manual edits.
- [ ] Re-run service tests and verify they pass.

### Task 3: CLI Wiring

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Test: `tests/test_cli.py`

- [ ] Write failing CLI tests for `jczq-debate-init --date ... --output-dir ... --format json`, `jczq-debate-compare`, and `jczq-debate-finalize`.
- [ ] Add `build_jczq_debate_workspace_service()` and the three Typer commands.
- [ ] Commands should return JSON payloads when `--format json` is passed and print key artifact paths in text mode.
- [ ] Re-run focused CLI tests and verify they pass.

### Task 4: Verification

**Files:**
- No production changes expected.

- [ ] Run `uv run pytest tests/test_jczq_debate_service.py tests/test_cli.py::<focused tests> -q`.
- [ ] Run `python3 -m compileall nutmeg`.
- [ ] Run `git diff --check`.
- [ ] Summarize created files, commands, and remaining Phase 2 limits.
