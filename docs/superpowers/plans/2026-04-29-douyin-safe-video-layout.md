# Douyin Safe Video Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Remotion captions, cards, and disclaimer into a Douyin-safe layout and rerender the 周三009 video without new Seedance spend.

**Architecture:** Add shared layout constants in `video/remotion/src/safeLayout.ts`, consume them from `CaptionTrack`, `ScreenCard`, and `Disclaimer`, then rerender with existing props/assets. Keep video production data unchanged.

**Tech Stack:** TypeScript/React/Remotion, pytest static regression test, npm typecheck, ffmpeg/ffprobe QC.

---

### Task 1: Safe Layout Constants

**Files:**
- Test: `tests/test_remotion_service.py`
- Create: `video/remotion/src/safeLayout.ts`
- Modify: `video/remotion/src/components/CaptionTrack.tsx`
- Modify: `video/remotion/src/components/ScreenCard.tsx`
- Modify: `video/remotion/src/components/Disclaimer.tsx`

- [ ] Add a failing pytest regression for Douyin safe layout constants and component imports.
- [ ] Run the focused pytest and confirm it fails because `safeLayout.ts` is missing.
- [ ] Add `safeLayout.ts` with constants for margins, card top, caption bottom, disclaimer bottom, and right reserve.
- [ ] Update CaptionTrack, ScreenCard, and Disclaimer to import and use the constants.
- [ ] Run the focused pytest and typecheck.

### Task 2: Rerender 周三009 v7

**Files:**
- Input: `.nutmeg-data/daily-content-analysis/20260429/run-125848/post17-video-prep/周三009/remotion-timeline-with-extended-mood-public.json`
- Input audio: `.nutmeg-data/daily-content-analysis/20260429/run-125848/post17-video-prep/周三009/audio-repair-v6-controlled-breaks/voiceover-cosyvoice-v6-controlled-breaks-60s.wav`
- Output: `.nutmeg-data/daily-content-analysis/20260429/run-125848/post17-video-prep/周三009/videos/final-post17-周三009-v7-douyin-safe-layout-cosyvoice-no-bgm.mp4`

- [ ] Render Remotion v7 with existing extended mood props.
- [ ] Mux v6 controlled-break audio.
- [ ] Run ffprobe, full ffmpeg decode, and silencedetect.
- [ ] Generate QC contact sheet.
- [ ] Write final output doc and memory note.
