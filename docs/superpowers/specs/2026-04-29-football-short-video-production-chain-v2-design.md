# Football Short Video Production Chain v2 Design

**Date:** 2026-04-29  
**Owner:** Nutmeg / Jun  
**Status:** Draft for user review  
**Scope:** Redesign the daily football short-video workflow from full-AI animation into a higher-quality short-form sports explainer pipeline.

## 1. Background

The 2026-04-28 PSG vs Bayern experiment proved the end-to-end path can run: daily analysis, Seedance submission, polling/download, local concat, TTS, and final MP4 export. It also exposed production-quality limits:

- full-length Seedance animation is hard to control for text, jersey marks, numbers, watermarks, and continuity;
- retro manga / FC-style visuals do not consistently feel premium or credible for赛前分析;
- patching generated video with blank masks creates new visual noise;
- script quality needs stronger short-video hooks instead of reading analysis notes;
- TTS should be continuous and directed like a sports narrator, not segmented per 10-second clip;
- professional tactical explanation should be deterministic and locally controlled, not left to a generative video model.

The new direction is **Route C: animation hook + tactical motion explainer + emotional closing**, positioned as **短视频爆点解说栏目 + 专业赛前情报栏目**.

## 2. Product Positioning

### Column Identity

**Working title:** `一分钟赛前战术变量`  
**Promise:** In one minute, explain the one variable that may decide the match.

### Viewer Feeling

The viewer should feel:

1. the opening has a real short-video hook;
2. the middle explains one concrete football variable clearly;
3. the account is professional and restrained, not gambling-hype content;
4. the visuals feel like a premium sports explainer, not random AI animation.

### Content Tone

Default tone is **反常识型**:

> 表面看是 A，其实真正决定比赛的是 B。

For major matches, occasionally use **强冲突型**:

> 这场最大的危险不是 A，而是 B。

Avoid deterministic betting language such as `稳了`, `必红`, `稳赢`, `比分锁定`, `上车`, `红单`, `跟我买`.

## 3. Visual Direction

### Main Style

**Cinematic Sports Anime x Broadcast Tactics**  
中文定位：**电影感足球番剧 + 高级战术转播包装**

This is not a full cartoon episode. It is a sports explainer with cinematic anime mood shots.

### Seedance Visual Role

Seedance should only generate high-quality mood shots:

- player eyes / boots / ball closeups;
- sprinting, pressing, tracking-back, duel moments;
- stadium lights, grass, tunnel, crowd bokeh;
- emotional ending shots.

Seedance must not generate:

- readable text, Chinese characters, English letters, numbers;
- captions, title cards, UI, speech bubbles, tactical labels;
- tactical boards with symbols that look like text;
- scoreboards with digits;
- real club crests, real sponsors, real player likenesses;
- kit closeups that create fake logos or fake text.

### Local Visual Role

Local postproduction owns the professional information layer:

- opening title/hook text;
- dynamic tactical pitch map;
- pressure zones, passing lanes, transition arrows;
- keyword cards;
- subtitles;
- disclaimer;
- timing and transitions.

The local layer should feel like premium sports broadcast graphics: clean, fast, readable, with restrained motion.

## 4. Target 60-Second Structure

Each video explains **one main contradiction**.

| Time | Segment | Goal | Visual Owner |
| --- | --- | --- | --- |
| 0-3s | Hook | Stop scroll with反常识/强冲突判断 | Seedance mood shot + local title |
| 3-8s | Match setup | Establish teams and core conflict | Seedance mood shot + subtitle |
| 8-25s | Variable 1 | Explain why the first tactical variable matters | Remotion tactical map |
| 25-40s | Variable 2 | Explain opponent counter or failure condition | Remotion tactical map + Seedance insert |
| 40-52s | Risk check | Add market/tempo/lineup caveat without betting instruction | Local graphics + brief mood shot |
| 52-60s | Closing | Tell viewers what to watch, then responsible-use note | Emotional Seedance shot + subtitle |

### Example Hook Patterns

反常识型:

- `这场表面看是主场优势，其实真正决定比赛的是压迫会不会断档。`
- `别只看谁控球多，这场更关键的是谁先把球逼到边线。`

强冲突型:

- `这场最大的危险，不是拜仁控球，而是巴黎压上之后身后被一脚打穿。`
- `这场最容易误判的地方，是把主场优势当成绝对优势。`

## 5. Production Architecture

### 5.1 Content Brain

**Responsibility:** Turn match data and analysis into short-video-native content.

Inputs:

- match metadata;
- popularity/focus level;
- tactical read;
- market read as public-observation caveat only;
- compliance constraints.

Outputs:

- 3 hook candidates;
- selected hook type: `counterintuitive` or `conflict`;
- one main contradiction;
- 60-second voiceover script;
- visual beat plan;
- compliance notes.

Quality rule:

- If the script cannot be summarized as one sentence, it is too broad.

### 5.2 Director

**Responsibility:** Decide which visual system renders each beat.

Outputs:

- shot list;
- Seedance mood-shot prompt list;
- Remotion tactical timeline plan;
- subtitle timing plan;
- audio timing target.

Rules:

- Use Seedance for emotion and motion, not information.
- Use Remotion for tactical explanation and all text.
- Avoid generating more Seedance clips than needed. Default is 3 mood clips, not 6 full story clips.

### 5.3 Seedance Mood Shot Generator

**Responsibility:** Generate clean, reusable cinematic football mood shots.

Default shot types:

1. opening closeup: ball / boots / eyes / tunnel;
2. pressure or counterattack action insert;
3. emotional closing shot.

Prompt strategy:

- short, shot-specific prompts;
- no text/no numbers/no logos constraints;
- avoid jersey-front and jersey-back closeups;
- avoid scoreboards and tactical boards;
- specify empty/abstract kits and no chest marks.

Output:

- individual MP4 mood clips;
- preview contact sheet;
- QC flags for text artifacts, logos, and continuity.

### 5.4 Remotion Tactical Explainer

**Responsibility:** Render the deterministic final visual timeline.

Why Remotion:

- React-based reusable components;
- programmatic video rendering;
- better for typography, captions, motion graphics, and templates than ad-hoc MoviePy;
- easier to build a stable column identity.

Core components:

- `OpeningHook`: title, match, conflict line;
- `PitchMap`: football pitch with team shapes;
- `PressureWave`: animated pressing zone;
- `PassingLane`: arrows and ball movement;
- `CounterRun`: opponent transition routes;
- `KeywordCard`: 1-3 keywords;
- `CaptionTrack`: Chinese subtitle line timing;
- `Disclaimer`: responsible-use note;
- `MoodShotLayer`: embeds Seedance clips in designated windows.

Visual rules:

- only 1-3 keywords per screen;
- subtitles must not cover tactical focus area;
- use high contrast and large type for mobile;
- avoid over-decorating with UI noise.

### 5.5 Voice and Audio

**Responsibility:** Create a continuous narrator track with short-video rhythm.

Default:

- CosyVoice Chinese female voice for local/offline production;
- one continuous master audio file;
- no 10-second slot silence;
- no local BGM baked into the master;
- BGM selected in Douyin at publish time.

Future provider candidates:

- Volcengine/MegaTTS or other commercial Chinese TTS if CosyVoice quality remains insufficient;
- voice style should be energetic but credible, not overdramatic.

Script delivery rules:

- shorter sentences;
- clear stress words;
- no academic phrasing;
- no betting command language.

### 5.6 FFmpeg Finalizer

**Responsibility:** Final mux/transcode and technical verification.

Tasks:

- combine Remotion-rendered video and voiceover;
- normalize output settings;
- verify duration, frame rate, resolution, audio stream;
- run full decode check;
- write final artifact manifest.

## 6. Daily Output Artifacts

Each selected match should produce:

```text
matches/<match_id>/
  content-brief.json
  hooks.json
  voiceover-script.md
  director-shotlist.json
  seedance-mood-manifest.json
  remotion-timeline.json
  captions.srt
  quality-report.json
  videos/
    mood-shot-01.mp4
    mood-shot-02.mp4
    mood-shot-03.mp4
    final-master.mp4
```

Run-level output:

```text
run-<time>/
  daily-content-report.md
  production-dashboard.json
  selected-matches.json
  publish-checklist.md
```

## 7. Quality Gates

### Content Gate

- Hook is understandable in under 3 seconds.
- Script has one main contradiction.
- Public-facing text avoids deterministic result claims.
- Compliance disclaimer exists.

### Visual Gate

- No generated text artifacts in Seedance clips.
- No fake logos, fake sponsors, or jersey numbers in closeup.
- Tactical graphics are readable on phone screen.
- No blank masks or production-note overlays.
- Visual pacing changes at least every 6-8 seconds.

### Audio Gate

- Voiceover is continuous.
- No repeated 10-second gaps.
- No obvious voice gender drift.
- Narration sounds like short-video commentary, not document reading.

### Final Technical Gate

- 9:16 vertical output.
- Target duration 45-60 seconds.
- AAC audio present.
- Full ffmpeg decode passes.
- Quality report is written.

## 8. Implementation Phases

### Phase 1: Prototype Spec, No New Provider Spend

Build one complete sample package as JSON/spec first:

- hook candidates;
- script;
- shot list;
- Remotion timeline plan;
- Seedance mood prompts;
- QC checklist.

No Seedance task is submitted in this phase.

### Phase 2: Remotion Template Spike

Build a local Remotion proof of concept using placeholder video or existing clips:

- animated pitch map;
- opening hook title;
- captions;
- mood-shot windows;
- final MP4 render.

### Phase 3: One-Match End-to-End Test

Use one real match and generate:

- 2-3 Seedance mood shots;
- continuous TTS;
- Remotion final video;
- QC report.

### Phase 4: Daily Production Integration

Wire the new chain into Nutmeg daily content workflow:

- select popular matches;
- create production packets;
- render final outputs;
- track costs and failures;
- keep old Seedance manifest flow as fallback.

## 9. Risks and Mitigations

### Risk: Seedance still creates text artifacts

Mitigation:

- only use mood shots with fewer surfaces where fake text appears;
- avoid shirt closeups, boards, scoreboards, and signs;
- QC and regenerate only failed mood shots;
- keep Remotion as the final timeline owner.

### Risk: Remotion adds frontend toolchain complexity

Mitigation:

- isolate under `video/remotion/` or `tools/remotion/`;
- keep Python as orchestration layer;
- exchange data through JSON timeline specs;
- do not rewrite existing Python services in TypeScript.

### Risk: Content becomes clickbait

Mitigation:

- hook can be sharp, but the body must explain evidence;
- no guaranteed outcomes;
- no betting commands;
- disclaimer remains in every public script.

### Risk: Production time is too high per match

Mitigation:

- start with one premium match per day;
- use 30-45s lightweight version for secondary matches later;
- reuse Remotion templates and Seedance prompt families.

## 10. Recommended First Prototype

Prototype the route on one match only:

- duration: 60 seconds;
- style: Cinematic Sports Anime x Broadcast Tactics;
- hook type: counterintuitive by default;
- Seedance mood shots: 3;
- Remotion tactical segments: 2;
- TTS: continuous Chinese female voice;
- no local BGM;
- final output: one MP4 plus quality report.

The prototype should be judged on whether it feels like a premium short-form football explainer, not whether it looks like a complete cartoon episode.

## 11. External References Used

- TikTok creative best practices: https://ads.tiktok.com/help/article/creative-best-practices
- TikTok creative guide: https://ads.tiktok.com/business/en/guides/what-is-ad-creative-guide
- Short-form football analysis discussion: https://breakingthelines.com/opinion/deep-dives-in-a-short-form-world-can-football-analysis-thrive-on-tiktok-and-x/
- Football tactics on TikTok discussion: https://www.meer.com/en/97452-how-tiktok-is-changing-how-we-talk-about-football
- DrawTactics animated tactics reference: https://drawtactics.com/blog/product/how-to-create-animated-football-tactics
- Remotion: https://www.remotion.dev/
- Remotion TikTok captions template: https://github.com/remotion-dev/template-tiktok
- MoviePy: https://github.com/Zulko/moviepy
- mplsoccer pitch docs: https://mplsoccer.readthedocs.io/en/latest/mplsoccer.pitch.html
- Kloppy: https://github.com/pySport/kloppy
