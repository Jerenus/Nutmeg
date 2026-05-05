# JCZQ Daily Iteration Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily JCZQ review write executable strategy policy and make the daily advisor consume it.

**Architecture:** Extend `nutmeg/services/jczq_strategy_memory.py` with a normalized `decision_policy` derived from reviewed results and graded legs. Keep the 08:00 launchd command unchanged by preserving `jczq-daily-review` as the orchestration entry point, then update `nutmeg/services/jczq_daily.py` to apply active policy rules during plan building and summary rendering.

**Tech Stack:** Python 3.12, Typer CLI, pytest, local JSON artifacts, existing launchd plist.

---

### Task 1: Policy Generation In Review Memory

**Files:**
- Modify: `tests/test_jczq_review_service.py`
- Modify: `nutmeg/services/jczq_strategy_memory.py`

- [x] Write a failing test that `jczq-daily-review` writes `decision_policy` with active strong-banker downgrade, 2-goal promotion, half-full downgrade, and reuse guard.
- [x] Run `uv run pytest tests/test_jczq_review_service.py::test_daily_review_writes_executable_decision_policy -q` and confirm it fails because `decision_policy` is missing.
- [x] Implement policy normalization and update helpers in `jczq_strategy_memory.py`.
- [x] Re-run the focused review test and confirm it passes.

### Task 2: Policy Consumption In Daily Advisor

**Files:**
- Modify: `tests/test_jczq_daily_service.py`
- Modify: `nutmeg/services/jczq_daily.py`

- [x] Write a failing test that a memory policy downgrades cold strong bankers, promotes 2-goal legs, and surfaces policy notes in the advisor summary.
- [x] Run `uv run pytest tests/test_jczq_daily_service.py::test_daily_advisor_applies_executable_decision_policy -q` and confirm it fails on current behavior.
- [x] Implement advisor policy helpers and apply them after existing revision/memory overrides and before comfort-risk protection.
- [x] Re-run the focused advisor test and confirm it passes.

### Task 3: Operational Verification

**Files:**
- Verify: `scripts/launchd/com.nutmeg.jczq.daily-review-8am.plist`
- Verify: `tests/test_jczq_review_service.py`
- Verify: `tests/test_jczq_daily_service.py`

- [x] Confirm the 08:00 plist still runs `jczq-daily-review --date yesterday --output-dir .nutmeg-data/jczq --dispatch-telegram --no-dry-run`.
- [x] Run focused tests for review, advisor, and CLI wiring: `uv run pytest tests/test_jczq_review_service.py tests/test_jczq_daily_service.py tests/test_cli.py::test_jczq_daily_review_command_dispatches_postmortem -q`.
- [x] Run `uv run ruff check nutmeg/services/jczq_strategy_memory.py nutmeg/services/jczq_daily.py nutmeg/services/jczq_review.py tests/test_jczq_review_service.py tests/test_jczq_daily_service.py`.
- [x] Run `python3 -m compileall nutmeg/services/jczq_strategy_memory.py nutmeg/services/jczq_daily.py nutmeg/services/jczq_review.py`.

## Self-Review

Spec coverage: The tasks cover policy generation, policy consumption, and operational verification of the existing 08:00 entry point. Placeholder scan: No placeholder implementation steps are left. Type consistency: The plan consistently uses `decision_policy`, `jczq-daily-review`, and `JczqDailyAdvisorService`.
