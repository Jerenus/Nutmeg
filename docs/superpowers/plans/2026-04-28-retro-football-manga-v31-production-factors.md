# Retro Football Manga v3.1 Production Factors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the approved v3.1 retro football manga short-video factors part of daily content artifacts and Seedance manifests.

**Architecture:** Keep generation local and review-first. Extend the existing `DailyContentService` constants/storyboard/manifest rendering instead of adding a new provider boundary. Store canonical style docs under `docs/style-assets/retro-football-manga-v3.1/` and expose a runtime copy under `.nutmeg-data/style-assets/retro-football-manga-v3.1/`.

**Tech Stack:** Python 3.12, dataclasses, JSON/Markdown artifacts, pytest, ruff, compileall.

---

### Task 1: Add failing tests for v3.1 production factors

**Files:**
- Modify: `tests/test_daily_content_service.py`

- [ ] Add a test that builds a sample run and asserts `run.style_profile == "retro-football-manga-v3.1"`.
- [ ] Assert the manifest has `production_factors`, `quality_gates`, and `platform_outputs`.
- [ ] Assert at least one Seedance prompt contains `原创80年代复古少年足球漫画动画`, `前2秒强钩子`, `固定栏目包装`, and `精修赛璐璐动画`.
- [ ] Assert per-match `production-factors.json` is written.
- [ ] Run the test and verify it fails before implementation.

### Task 2: Implement daily-content v3.1 factors

**Files:**
- Modify: `nutmeg/services/daily_content.py`

- [ ] Update style constants to v3.1.
- [ ] Add production-factor, quality-gate, platform-output, and prompt constants.
- [ ] Update storyboard beats to the v3.1 structure.
- [ ] Update Seedance prompts to include positive style, continuity, platform, safety, and negative prompt factors.
- [ ] Include production metadata in manifest and per-match artifacts.
- [ ] Run focused tests until green.

### Task 3: Create canonical v3.1 style assets

**Files:**
- Create: `docs/style-assets/retro-football-manga-v3.1/README.md`
- Create: `docs/style-assets/retro-football-manga-v3.1/style-bible.md`
- Create: `docs/style-assets/retro-football-manga-v3.1/episode-template.md`
- Create: `docs/style-assets/retro-football-manga-v3.1/prompt-template.md`
- Create: `docs/style-assets/retro-football-manga-v3.1/series-packaging.md`
- Create: `docs/style-assets/retro-football-manga-v3.1/shot-library.md`
- Create: `docs/style-assets/retro-football-manga-v3.1/platform-output.md`
- Create: `docs/style-assets/retro-football-manga-v3.1/quality-checklist.md`
- Create: `docs/style-assets/retro-football-manga-v3.1/team-injection-schema.json`

- [ ] Write the approved style, episode, prompt, platform, and quality rules.
- [ ] Validate `team-injection-schema.json` with `python3 -m json.tool`.
- [ ] Copy the canonical directory to `.nutmeg-data/style-assets/retro-football-manga-v3.1/` for runtime use.

### Task 4: Verification and memory

**Files:**
- Modify: `memory/2026-04-28.md`

- [ ] Run focused daily-content tests.
- [ ] Run `uv run ruff check nutmeg/services/daily_content.py tests/test_daily_content_service.py`.
- [ ] Run `python3 -m compileall nutmeg/services/daily_content.py`.
- [ ] Record the v3.1 decision in daily memory.
