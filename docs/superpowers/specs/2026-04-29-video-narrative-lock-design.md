# Video Narrative Lock Design

## Problem

Recent football short videos can look polished while still feeling hard to follow because voiceover, screen text, and visuals are generated from separate fields. The audience hears one sentence, sees a different tactical card, and watches a mood shot that is only broadly related. This breaks comprehension and makes users "跟丢".

## Goal

Introduce a Narrative Lock layer so every 60-second video is driven by a single timecoded narrative timeline. Voiceover, subtitles, screen cards, tactical map focus, and Seedance mood-shot intent must all derive from the same segment list.

## Scope

- Add `NarrativeSegment` and `NarrativeTimeline` domain objects.
- Make `ProductionPacketV2` carry the narrative timeline.
- Generate a fixed six-segment 60-second story arc for football explainers.
- Export `narrativeSegments` in Remotion props.
- Render screen text and captions from `narrativeSegments`, not from independent ad-hoc strings.
- Add QC checks that flag missing segments, mismatched subtitles, and orphan screen text.
- Regenerate one 周三003 comparison master to validate the improved narrative alignment.

## Non-Goals

- Do not change the provider strategy: Seedance remains mood-shot-only and must not render readable text.
- Do not bake background music; Douyin platform music remains selected during publishing.
- Do not build automatic speech-to-text alignment yet. This version uses deterministic segment timing from the script.

## Narrative Structure

The 60-second timeline uses six segments:

1. `hook` 0-6s: counterintuitive match framing.
2. `variable` 6-16s: first tactical variable.
3. `why` 16-28s: why the first variable matters.
4. `counter` 28-40s: the opponent's counter-path.
5. `risk` 40-52s: live match observation points.
6. `closing` 52-60s: summary plus responsible-use disclaimer.

Each segment stores:

- `segment_id`
- `start_seconds`
- `end_seconds`
- `scene_type`
- `voiceover_text`
- `subtitle_text`
- `screen_card_text`
- `visual_intent`
- `tactical_focus`
- `transition_to_next`

## Data Flow

`InternalAnalysis + PublicScript` -> `ContentBrainResult` -> `NarrativeTimeline` -> `ProductionPacketV2` -> artifacts:

- `voiceover-script.md`: concatenated segment `voiceover_text`
- `narrative-timeline.json`: canonical locked timeline
- `remotion-timeline.json`: includes `narrativeSegments`
- `seedance-mood-manifest.json`: mood prompts reference scene intent but still forbid text/logos/numbers

## Quality Gates

A production packet should be marked `review` if:

- segment coverage is not exactly 0-60s;
- any subtitle is not derived from the corresponding voiceover text;
- any screen card is empty or too long;
- any Remotion caption/card text cannot be traced to a narrative segment;
- any mood shot prompt asks Seedance to render readable text.

## Acceptance Criteria

- Tests prove narrative segments serialize and are included in packet/timeline artifacts.
- Tests prove Remotion reads `narrativeSegments` and no longer hardcodes unrelated closing copy.
- 周三003 comparison master uses a single narrative timeline for script, subtitles, and screen text.
- Final video validates with ffprobe, full ffmpeg decode, and silence scan.
