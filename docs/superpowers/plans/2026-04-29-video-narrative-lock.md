# Video Narrative Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make football short-video voiceover, subtitles, screen cards, and tactical visuals derive from one timecoded narrative timeline.

**Architecture:** Add a domain-level `NarrativeTimeline` to `ProductionPacketV2`, have `VideoProductionService` generate six locked segments, write `narrative-timeline.json`, and pass `narrativeSegments` into Remotion. Remotion renders captions/cards by current segment so visual text follows the voiceover instead of independent labels.

**Tech Stack:** Python 3.12 dataclasses, pytest, Typer CLI artifacts, TypeScript/React Remotion, FFmpeg validation.

---

### Task 1: Domain And Service Narrative Timeline

**Files:**
- Modify: `nutmeg/domain/daily_content.py`
- Modify: `nutmeg/services/video_production.py`
- Test: `tests/test_video_production_service.py`

- [ ] **Step 1: Write failing tests**

Add tests asserting `NarrativeSegment` serializes, `ProductionPacketV2.to_dict()` includes `narrative_timeline`, generated packet has six contiguous segments, and `voiceover_script` equals joined segment voiceover text.

- [ ] **Step 2: Run test to verify RED**

Run: `uv run pytest tests/test_video_production_service.py -q`
Expected: FAIL because narrative classes/fields do not exist.

- [ ] **Step 3: Implement minimal domain/service code**

Add `NarrativeSegment`, `NarrativeTimeline`, `narrative_timeline` on `ProductionPacketV2`, `_narrative_timeline()`, and include `narrativeSegments` in Remotion props plus `narrative-timeline.json` artifact.

- [ ] **Step 4: Run test to verify GREEN**

Run: `uv run pytest tests/test_video_production_service.py -q`
Expected: PASS.

### Task 2: Remotion Narrative Rendering

**Files:**
- Modify: `video/remotion/src/schema.ts`
- Modify: `video/remotion/src/Root.tsx`
- Modify: `video/remotion/src/components/CaptionTrack.tsx`
- Create or modify: `video/remotion/src/components/ScreenCard.tsx`
- Test: `tests/test_remotion_service.py`

- [ ] **Step 1: Write failing tests**

Add tests asserting schema has `NarrativeSegmentSchema`, Root renders from `narrativeSegments`, and the old hardcoded closing caption is gone.

- [ ] **Step 2: Run test to verify RED**

Run: `uv run pytest tests/test_remotion_service.py -q`
Expected: FAIL because Remotion does not yet define narrative segment schema/rendering.

- [ ] **Step 3: Implement Remotion changes**

Add schema fields, derive current segment by sequence, render `subtitle_text` and `screen_card_text`, and keep mood shots/tactical maps aligned to segment windows.

- [ ] **Step 4: Verify TypeScript and tests**

Run: `uv run pytest tests/test_remotion_service.py -q` and `npm --prefix video/remotion run typecheck`.
Expected: PASS.

### Task 3: 周三003 Comparison Master

**Files/Artifacts:**
- Runtime: `.nutmeg-data/daily-content-cases/20260429/run-105540/matches/周三003/production-v2/`
- Runtime: `.nutmeg-data/daily-content-cases/20260429/run-105540/matches/周三003/videos/`

- [ ] **Step 1: Regenerate production packet artifacts for 周三003**

Use existing `analysis.json` and `public-script.md` data to refresh narrative timeline props without resubmitting Seedance.

- [ ] **Step 2: Render Remotion comparison video**

Run `uv run nutmeg video-render` using `remotion-timeline-with-mood-public.json` and output `remotion-v2-narrative-lock-with-seedance-mood.mp4`.

- [ ] **Step 3: Reuse existing CosyVoice audio or generate aligned audio from joined narrative script**

Mux to `final-v2-narrative-lock-cosyvoice-no-bgm.mp4`.

- [ ] **Step 4: Verify final media**

Run ffprobe, full ffmpeg decode, and silence scan.

### Task 4: Full Verification And Record

**Files:**
- Modify: `memory/2026-04-29.md`

- [ ] **Step 1: Run checks**

Run: `uv run ruff check .`, `uv run pytest -q`, `npm --prefix video/remotion run typecheck`.

- [ ] **Step 2: Record decisions and output path**

Append memory with the Narrative Lock change and comparison artifact path.

- [ ] **Step 3: Commit source/doc changes**

Commit only tracked source/test/docs/memory files, not generated media or ignored mood shots.
