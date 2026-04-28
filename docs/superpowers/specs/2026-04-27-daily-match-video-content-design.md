# Daily Match Video Content Design

**Date:** 2026-04-27  
**Status:** Draft for user review  
**Chosen approach:** Content-first workflow with semi-automatic Seedance video generation

## Goal

Build a Nutmeg daily production workflow that turns every热门竞彩足球 match on a slate into an independent analysis-and-video package: internal match analysis, public-safe 60-second script, animation storyboard, Seedance 2.0 prompt manifest, and reviewable daily delivery documents. Video generation is semi-automatic: Nutmeg prepares everything first, then submits video jobs only after explicit operator confirmation.

## Decisions Captured

- Coverage: all热门 matches for the day, not only the top few. If the slate has 9 popular matches, generate 9 match packages.
- Animation style: original hot-blooded football anime plus tactical-data manga overlays.
- Automation: semi-automatic. Generate documents, scripts, storyboards, and prompts first; submit Seedance jobs after review.
- Output ratio: vertical 9:16 first, with horizontal 16:9 prompts preserved for later compilations.
- Segment strategy: hybrid. Ordinary popular matches use 4 segments x 15 seconds; focus/conflict matches use 6 segments x 10 seconds.
- Compliance model: layered output. Internal documents may include odds, JCZQ lean, handicap protection, confidence, and risk; public scripts must stay as sports analysis and market-expectation commentary without betting actions or profit language.

## Current Project Fit

Nutmeg already has most upstream pieces:

- `nutmeg.services.jczq` and `jczq-mixed-report` can fetch/load Sporttery calculator-style official odds and write report artifacts.
- API-Football live context is already usable for fixture IDs, standing/form/H2H sanity checks, and match metadata.
- `nutmeg.services.content` already has structured content generation, deterministic fallback, disclaimers, and compliance checks.
- Existing artifact conventions write JSON/Markdown/PDF under `.nutmeg-data`.
- OpenClaw router already exposes allowlisted Nutmeg actions with confirmation gates for write/dispatch operations.

The new work should add a production layer rather than duplicate football logic.

## Proposed User Workflow

### 1. Generate The Daily Review Pack

Operator runs:

```bash
uv run nutmeg daily-content-pack \
  --date today \
  --provider live \
  --scope popular-all \
  --pdf \
  --llm-mode openclaw \
  --format json
```

Expected result:

- Fetch or load the day's JCZQ slate.
- Select all热门 matches based on existing popularity and sellability rules.
- Build one `MatchContentPack` per match.
- Write a daily JSON manifest, Markdown review document, and optional PDF.
- Write per-match Seedance task specs but do not submit them.

### 2. Review And Edit

Operator reviews:

```text
.nutmeg-data/daily-content/YYYYMMDD/run-<timestamp>/daily-match-content-YYYYMMDD.md
.nutmeg-data/daily-content/YYYYMMDD/run-<timestamp>/daily-match-content-YYYYMMDD.pdf
.nutmeg-data/daily-content/YYYYMMDD/run-<timestamp>/seedance-manifest.json
```

The Markdown document should be human-editable and contain:

- Daily slate summary.
- Per-match internal analysis.
- Public-safe short-video script.
- Storyboard segments.
- Vertical prompt.
- Horizontal prompt.
- Compliance result.
- Evidence freshness warnings.

### 3. Submit Video Jobs After Confirmation

Operator runs:

```bash
uv run nutmeg seedance-submit \
  --manifest .nutmeg-data/daily-content/YYYYMMDD/run-<timestamp>/seedance-manifest.json \
  --confirm \
  --max-concurrency 2 \
  --format json
```

Expected result:

- Submit only reviewed Seedance segment tasks.
- Save one provider task ID per segment.
- Persist updated manifest/status file.
- Do not post videos externally.

### 4. Poll And Download Results

Operator runs:

```bash
uv run nutmeg seedance-poll \
  --run-dir .nutmeg-data/daily-content/YYYYMMDD/run-<timestamp> \
  --download \
  --format json
```

Expected result:

- Query Seedance task statuses.
- Download successful segment MP4s before provider URLs expire.
- Save failures with error messages for retry.
- If `ffmpeg` is available, optionally concatenate per-match segment videos into a final 60-second MP4.

## Output Directory Contract

Each daily run writes a self-contained directory:

```text
.nutmeg-data/daily-content/YYYYMMDD/run-YYYYMMDD-HHMMSS/
  daily-match-content-YYYYMMDD.json
  daily-match-content-YYYYMMDD.md
  daily-match-content-YYYYMMDD.pdf
  seedance-manifest.json
  seedance-status.json
  matches/
    <match_id>/
      analysis.json
      public-script.md
      storyboard.md
      seedance-vertical.json
      seedance-horizontal.json
      compliance.json
      videos/
        segment-01.mp4
        segment-02.mp4
        segment-03.mp4
        segment-04.mp4
        final-vertical.mp4
```

If a match uses 6 segments, the `videos/` folder includes `segment-01.mp4` through `segment-06.mp4`.

## Domain Model

### DailyContentRun

Represents one daily content production run.

Fields:

- `run_id`: stable run identifier, e.g. `daily-content-20260427-173000`.
- `run_date`: local slate date in `YYYY-MM-DD`.
- `generated_at`: ISO timestamp.
- `provider`: `live` or `sample`.
- `scope`: `popular-all` for this version.
- `style_profile`: reference to the daily animation style bible.
- `matches`: list of `MatchContentPack`.
- `artifacts`: JSON/Markdown/PDF/manifest paths.
- `warnings`: run-level freshness, missing data, or provider warnings.

### MatchContentPack

Represents one match's complete content package.

Fields:

- `match_id`, `match_no`, `competition`, `home_team`, `away_team`, `kickoff_time`.
- `popularity_score`, `focus_level`: `standard` or `focus`.
- `internal_analysis`: structured football/odds analysis.
- `public_script`: public-safe 60-second script.
- `storyboard`: `VideoStoryboard`.
- `seedance_specs`: vertical and horizontal `SeedanceTaskSpec` collections.
- `compliance`: risk level, reasons, checklist, publish recommendation.
- `evidence`: source ledger and update timestamps.
- `warnings`: match-level caveats.

### InternalAnalysis

Fields:

- `opening_read`: one-paragraph match framing.
- `football_factors`: recent form, home/away context, schedule pressure, tactical style.
- `market_factors`: odds movement, handicap warning, pool freshness, market contradiction.
- `key_risks`: list of uncertainty factors.
- `internal_lean`: internal JCZQ/odds lean, if evidence supports it.
- `confidence`: `low`, `medium`, or `high`.
- `responsible_use_note`: internal reminder that analysis is not a betting instruction.

### PublicScript

Fields:

- `title_candidates`: 3-5 Chinese titles.
- `hook`: 0-10 second opening.
- `body`: timed script blocks.
- `closing`: 55-60 second responsible-use closer.
- `voiceover_text`: final public narration text.
- `forbidden_terms_removed`: list of risky terms rewritten or removed.

Public script requirements:

- No explicit betting actions such as 买、跟、上车、梭哈、倍投.
- No profit or certainty claims such as 稳赚、包中、必中、回血、红单、连红.
- No private traffic or paid-plan lead-ins such as 私信、进群、拿方案、会员单.
- Odds may appear only as market-expectation context, not as instruction.
- Must include a responsible-use sentence: `以上只是赛前数据观察，不构成任何投注建议，理性看球。`

### VideoStoryboard

Fields:

- `style_profile_id`: e.g. `original-hotblood-tactical-manga-v1`.
- `ratio_primary`: `9:16`.
- `ratio_secondary`: `16:9`.
- `segment_count`: 4 or 6.
- `segments`: list of storyboard segments.

Each segment has:

- `segment_no`.
- `duration_seconds`: 10 or 15.
- `narration`.
- `visual_direction`.
- `camera_direction`.
- `tactical_overlay`.
- `subtitle_text`.
- `seedance_prompt_zh`.
- `seedance_prompt_en` optional if useful for model control.

### SeedanceTaskSpec

Fields:

- `task_key`: unique local key, e.g. `<match_id>-vertical-segment-01`.
- `provider`: `volcengine-ark`.
- `model`: default `doubao-seedance-2-0-260128`.
- `content`: Seedance content array.
- `resolution`: default `720p` for MVP.
- `ratio`: `9:16` or `16:9`.
- `duration`: 10 or 15.
- `seed`: deterministic integer for reproducibility.
- `camera_fixed`: false.
- `watermark`: true by default unless configured otherwise.
- `generate_audio`: false for MVP unless voice/audio strategy is explicitly enabled.
- `safety_identifier`: stable hashed local owner identifier, not raw personal data.
- `status`: local status such as `draft`, `submitted`, `running`, `succeeded`, `failed`, `downloaded`.
- `provider_task_id`: null until submitted.
- `output_video_url`: transient provider URL when available.
- `local_video_path`: downloaded MP4 path.
- `error`: provider error detail if failed.

## Style Bible

Style profile `original-hotblood-tactical-manga-v1`:

- Original 2D sports-anime-inspired football world, no existing IP references.
- Characters use fictional kits, fictional badges, and generic team color motifs only.
- Visual grammar: speed lines, burning grass trails, dramatic close-ups, tactical chalkboard overlays, data holograms, pass lanes, risk meters, and manga panel transitions.
- Keep players fictional. Do not recreate real footballer likenesses unless a future licensed-asset workflow exists.
- Avoid team logos, copyrighted mascots, protected uniforms, and direct references to known anime titles.
- Maintain daily continuity through the same color palette, line style, transitions, and recurring original narrator/analyst persona.

## Seedance Integration Notes

The integration should use current Volcengine Ark Seedance API behavior:

- Create task: `POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks`.
- Query task: `GET https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{id}`.
- Default model for quality: `doubao-seedance-2-0-260128`.
- Optional faster model later: `doubao-seedance-2-0-fast-260128`.
- Supported ratios include `9:16` and `16:9`.
- Seedance 2.0 segment duration range is 4-15 seconds, so 60-second output must be segmented.
- Query results expose `status`, `error`, `content.video_url`, `seed`, `resolution`, `ratio`, `duration`, and audio fields.
- Provider video URLs are temporary; downloaded local copies are required for durable daily output.

The code should keep API details in `nutmeg.services.seedance`, not in CLI commands or OpenClaw router.

Source references checked during design:

- Volcengine Ark create video task API: <https://www.volcengine.com/docs/82379/1520757>
- Volcengine Ark query video task API: <https://www.volcengine.com/docs/82379/1521309>
- Doubao Seedance 2.0 tutorial and model IDs: <https://www.volcengine.com/docs/82379/2291680>

## CLI Design

### daily-content-pack

Purpose: generate review pack and Seedance dry-run manifest.

Options:

- `--date`: `today` or explicit `YYYY-MM-DD`.
- `--provider`: `live` or `sample`.
- `--scope`: default `popular-all`.
- `--output-dir`: default `.nutmeg-data/daily-content`.
- `--llm-mode`: `deterministic` or `openclaw`.
- `--openclaw-model`: default `nyu-openai-chat/gpt-5.5`.
- `--pdf`: render PDF.
- `--format`: `text` or `json`.

### seedance-submit

Purpose: submit approved manifest tasks.

Options:

- `--manifest`: path to `seedance-manifest.json`.
- `--confirm`: required for real API submission.
- `--match-id`: optional subset.
- `--task-key`: optional single segment retry.
- `--max-concurrency`: default `2`.
- `--format`: `text` or `json`.

Without `--confirm`, command must refuse real submission and explain that video generation costs money.

### seedance-poll

Purpose: query statuses and optionally download videos.

Options:

- `--run-dir`: daily run directory.
- `--manifest`: optional explicit manifest path.
- `--download`: download successful provider URLs.
- `--concat`: attempt local concatenation when all segments for a match are downloaded.
- `--format`: `text` or `json`.

### seedance-retry

Optional MVP-plus command if time allows.

Purpose: resubmit only failed or expired segment tasks after prompt edits.

Options:

- `--run-dir`.
- `--match-id`.
- `--task-key`.
- `--confirm`.

## OpenClaw Router Design

Add allowlisted actions:

- `daily-content-pack`: safe to generate local review artifacts; live provider is allowed only when user explicitly asks for live/today.
- `seedance-submit`: real external paid generation; requires confirmation flag.
- `seedance-poll`: safe to query and download generated videos, but still external API if live provider is used.

Telegram bot behavior:

- `/dailycontent` creates the review pack and returns Markdown/PDF artifact paths or sends the PDF if dispatch is confirmed.
- `/seedance_submit <manifest>` refuses unless the message contains an explicit confirmation phrase or router confirm flag.
- `/seedance_poll <run_dir>` reports completed/failed/running counts and local video paths.

## Error Handling

- Missing live slate: write a failed run JSON with provider error and no video manifest.
- Missing API-Football context: continue with JCZQ-only analysis and add warning.
- Missing OpenClaw LLM: use deterministic script/storyboard fallback and mark `llm_status=fallback`.
- Compliance `HIGH` or `BLOCKED`: keep internal analysis, but mark public video script as not publishable and exclude its Seedance tasks unless `--include-blocked` is deliberately added in a future version. MVP should not include blocked scripts in the manifest.
- Missing `VOLCENGINE_ARK_API_KEY` or equivalent config: `seedance-submit` refuses with a setup message; `daily-content-pack` still succeeds in dry-run mode.
- Provider task failed: preserve provider error, keep prompt/spec, and allow targeted retry.
- Provider URL expired before download: mark as `expired_url` and require retry.
- `ffmpeg` missing: skip concatenation and leave downloaded segment MP4s intact.

## Testing Strategy

No-network tests:

- Domain serialization round-trips for `DailyContentRun`, `MatchContentPack`, `VideoStoryboard`, and `SeedanceTaskSpec`.
- Daily content service builds one pack per sample match and writes expected artifact files.
- Hybrid segmentation assigns 6 segments to focus matches and 4 segments to standard matches.
- Public script compliance blocks prohibited betting/profit/lead terms.
- Seedance dry-run manifest contains valid model, content, ratio, duration, and seed fields.
- `seedance-submit` refuses without `--confirm`.
- Fake Seedance provider returns submitted/running/succeeded/failed statuses and updates manifest state.
- Router rejects unconfirmed real video submission.

Live/manual smokes:

- `daily-content-pack --provider live --date today --pdf` generates the daily review pack without submitting video jobs.
- One-segment `seedance-submit --confirm --task-key ...` confirms API key, task creation, polling, and download.
- Full daily submission runs only after one-segment smoke succeeds.

Final verification:

```bash
uv run ruff check .
python3 -m compileall nutmeg scripts/openclaw
bash scripts/verify.sh
```

## Out Of Scope For MVP

- Direct posting to Douyin, WeChat, Bilibili, Xiaohongshu, or Telegram channels as public content.
- Betting execution, sportsbook links, guaranteed-profit claims, private group lead-ins, or paid picks.
- Real footballer likeness recreation or copyrighted club assets.
- Full Web review dashboard. Markdown/PDF/JSON review is sufficient for MVP.
- Advanced voiceover/TTS mixing. MVP can set `generate_audio=false` and keep narration text ready for later TTS.
- Fully automated daily cron. The workflow can become scheduled after manual review quality is proven.

## Acceptance Criteria

- A single command generates a reviewable daily package for all popular matches.
- Each match has internal analysis, public script, storyboard, vertical Seedance prompts, horizontal backup prompts, and compliance results.
- Public scripts are blocked or downgraded when they include forbidden betting/profit/lead language.
- Seedance tasks are never submitted without explicit confirmation.
- A confirmed submit command can create provider tasks and persist task IDs.
- Poll/download command can update statuses and save successful MP4 segments locally.
- Generated artifacts include enough metadata to reproduce a segment: model, prompt, ratio, duration, seed, timestamp, provider task ID.
- Tests and repository verification pass before claiming completion.

## Implementation Defaults

- API key lookup should support `VOLCENGINE_ARK_API_KEY` first and `ARK_API_KEY` as a compatibility fallback. Error messages should mention both names without printing secret values.
- MVP should use `generate_audio=false`. Narration remains text-first so a later TTS/audio-mixing workflow can control voice, pacing, and compliance separately.
- The daily PDF should include match analysis, public scripts, storyboard summaries, and compliance results. Full Seedance prompts should stay in JSON/Markdown artifacts to keep the PDF readable.
