# Betting Plan DB Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store finalized Jczq/Zucai betting plans in DuckDB and enrich next-day Jczq review with settled and same-play oracle odds.

**Architecture:** Add DuckDB tables and a focused repository for betting plans/reviews. Wire the Jczq daily advisor and Zucai report builders to optionally record final reports, and wire Jczq review to parse settled odds and write review rows. Keep existing JSON artifacts as the human-readable fallback.

**Tech Stack:** Python 3.12, DuckDB, Typer CLI, pytest, existing Nutmeg services and analytics schema.

**Status 2026-05-05:** Completed in current branch; verified with focused repository, Jczq daily/review, Zucai, CLI, and compile checks.

---

### Task 1: Betting Plan Repository

**Files:**
- Modify: `nutmeg/storage/bootstrap.py`
- Create: `nutmeg/storage/betting_plan_repository.py`
- Test: `tests/test_betting_plan_repository.py`

- [x] Add DuckDB schema for plan runs, plans, legs, plan reviews, and leg reviews.
- [x] Add a repository that idempotently records finalized Jczq reports.
- [x] Add a repository method that records Jczq review results with oracle odds.
- [x] Verify with a temp DuckDB database.

### Task 2: Jczq Advisor Recording

**Files:**
- Modify: `nutmeg/services/jczq_daily.py`
- Modify: `nutmeg/interfaces/cli.py`
- Test: `tests/test_jczq_daily_service.py`
- Test: `tests/test_cli.py`

- [x] Add an optional betting repository and `record_final` flag to daily advisor generation and revision.
- [x] Add `--record-final/--no-record-final` to the CLI with recording enabled by default.
- [x] Verify daily advisor can record to DB without changing existing JSON artifacts.

### Task 3: Jczq Review Odds And DB Backtest

**Files:**
- Modify: `nutmeg/services/jczq_review.py`
- Modify: `nutmeg/interfaces/cli.py`
- Test: `tests/test_jczq_review_service.py`

- [x] Parse settled odds from Okooo result rows into `*_odds` result fields.
- [x] Add actual odds to graded legs.
- [x] Persist review summaries to DuckDB when a repository is configured.
- [x] Render same-match/same-play oracle odds in the review message.

### Task 4: Zucai Final Plan Recording

**Files:**
- Modify: `nutmeg/services/zucai.py`
- Modify: `nutmeg/interfaces/cli.py`
- Test: `tests/test_zucai_service.py`
- Test: `tests/test_cli.py`

- [x] Add optional betting repository and `record_final` flag to Zucai report generation.
- [x] Record Zucai plan rows and selected match legs into the shared schema.
- [x] Keep existing Zucai grade command behavior unchanged.

### Task 5: Verification

**Files:**
- No production changes expected.

- [x] Run focused pytest files for betting repository, Jczq, Zucai, and CLI.
- [x] Run `python3 -m compileall nutmeg`.
- [x] Summarize changed files, verification output, and remaining limits.
