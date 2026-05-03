# JCZQ Review And Strategy Iteration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Solidify the 2026-05-01 postmortem lessons into the daily JCZQ strategy engine and run a Telegram postmortem every morning at 08:00.

**Architecture:** Extend `JczqDailyAdvisorService` with an explicit unchecked-popular-risk pass that detects non-banker 1.75-2.05 public favorites and injects draw/upset protection into the mixed plans. Add a focused review service that reads the prior day context, fetches result rows from OKOOO, grades saved legs, renders a Chinese postmortem, and dispatches it through the existing Telegram text sender. Expose the review service via CLI and install a launchd plist for 08:00 Asia/Shanghai.

**Tech Stack:** Python 3.12, Typer CLI, httpx/BeautifulSoup-style HTML parsing if already available, existing TelegramBotClient, pytest.

---

### Task 1: Strategy Risk Pass

**Files:**
- Modify: `nutmeg/services/jczq_daily.py`
- Test: `tests/test_jczq_daily_service.py`

- [ ] Add a failing test that a cautious favorite around 1.75-2.05 is not reused as an unchecked core leg across plans, and that draw/cold protection appears in final plans.
- [ ] Run the focused test and confirm it fails on current behavior.
- [ ] Implement `unchecked_popular` tagging and plan post-processing in `JczqDailyAdvisorService`.
- [ ] Re-run focused test and existing JCZQ daily tests.

### Task 2: Daily Review Service

**Files:**
- Create: `nutmeg/services/jczq_review.py`
- Create/modify: `nutmeg/domain/jczq_review.py` if domain models are clearer than dictionaries
- Modify: `tests/test_jczq_daily_service.py` or create `tests/test_jczq_review_service.py`

- [ ] Add a failing test with a fake result provider and saved context for 2026-05-01.
- [ ] Verify report grades legs including 003 平/负 success and highlights missed 005 suspicion/protection.
- [ ] Implement result provider parsing, grading, rendering, artifact writing, and Telegram text dispatch.
- [ ] Re-run review service tests.

### Task 3: CLI And Schedule

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Create: `scripts/launchd/com.nutmeg.jczq.daily-review-8am.plist`
- Test: `tests/test_cli.py`

- [ ] Add a failing CLI test for `jczq-daily-review --date yesterday --dispatch-telegram --no-dry-run` wiring.
- [ ] Add a failing test that launchd template runs at hour 8 minute 0 and uses real dispatch.
- [ ] Implement CLI builder, options, JSON output, and launchd plist.
- [ ] Re-run CLI and schedule tests.

### Task 4: Verification

**Files:**
- No production changes expected.

- [ ] Run `uv run pytest tests/test_jczq_daily_service.py tests/test_cli.py -q` or narrower equivalent if full CLI test is slow.
- [ ] Run `python3 -m compileall nutmeg`.
- [ ] Summarize changed files, strategy behavior, and any residual limits.
