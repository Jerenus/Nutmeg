# MoneyPrinterTurbo Video Worker Design

**Date:** 2026-05-07  
**Owner:** Nutmeg / Jun  
**Status:** Draft for user review  
**Decision:** Nutmeg remains the content brain and orchestration layer. MoneyPrinterTurbo runs as a local Docker API worker for video production.

## 1. Background

Nutmeg already has a sports short-video production chain:

- `DailyContentService` selects JCZQ matches and builds internal analysis, public scripts, compliance results, storyboards, and Seedance manifests.
- `VideoProductionService` writes `production-v2` artifacts such as `voiceover-script.md`, `director-shotlist.json`, `seedance-mood-manifest.json`, and `remotion-timeline.json`.
- Remotion renders deterministic tactical graphics and subtitles; Seedance is used only for mood shots.

That path is strong for premium tactical explainers, but it is relatively heavy for high-volume faceless content. MoneyPrinterTurbo is a mature open-source short-video generator that can take a subject or custom script and produce video copy, TTS, subtitles, material selection, BGM, and final short videos through Web UI or API.

For this integration, Nutmeg should not outsource judgment, compliance, or sports analysis to MoneyPrinterTurbo. Nutmeg should produce the final script and task intent, then submit a deterministic worker request to MoneyPrinterTurbo.

## 2. Goals

1. Use MoneyPrinterTurbo as an external local Docker worker for faceless video production.
2. Keep Nutmeg responsible for match selection, analysis, public script, compliance, and artifact lineage.
3. Add a clean adapter boundary so Nutmeg can call MoneyPrinterTurbo without coupling business logic to its implementation.
4. Persist every submitted request, task ID, status response, downloaded video URL/path, and quality result under the existing daily-content run directory.
5. Preserve the existing Remotion/Seedance v2 path as a premium fallback rather than replacing it.

## 3. Non-Goals

- Do not vendor or fork MoneyPrinterTurbo into this repository.
- Do not let MoneyPrinterTurbo regenerate or rewrite Nutmeg's final script in v1.
- Do not add account publishing, Douyin upload, or social scheduling.
- Do not require remote infrastructure; the first target is local Docker at `http://localhost:8080`.
- Do not submit external video jobs implicitly from content packet generation.

## 4. External Worker Assumptions

MoneyPrinterTurbo is run separately with Docker:

```bash
cd MoneyPrinterTurbo
docker compose up
```

Expected local endpoints:

- Web UI: `http://localhost:8501`
- API docs: `http://localhost:8080/docs`
- Create video: `POST /api/v1/videos` in the public docs, with implementation currently exposed by the FastAPI router as `/videos` unless the deployment applies a prefix.
- Query task: `GET /api/v1/tasks/{task_id}` in the public docs, with implementation currently exposed as `/tasks/{task_id}` unless the deployment applies a prefix.

Nutmeg should make the API prefix configurable instead of hardcoding one route shape. Default configuration should be:

```text
MPT_BASE_URL=http://localhost:8080
MPT_API_PREFIX=/api/v1
```

If a local deployment exposes unprefixed routes, the user can set:

```text
MPT_API_PREFIX=
```

Reference sources:

- MoneyPrinterTurbo repository: https://github.com/harry0703/MoneyPrinterTurbo
- MoneyPrinterTurbo README Docker/API notes: https://github.com/harry0703/MoneyPrinterTurbo#docker%E9%83%A8%E7%BD%B2-
- MoneyPrinterTurbo API docs mirror: https://mintlify.wiki/harry0703/MoneyPrinterTurbo/api/videos
- `TaskVideoRequest` schema source: https://raw.githubusercontent.com/harry0703/MoneyPrinterTurbo/main/app/models/schema.py
- video controller source: https://raw.githubusercontent.com/harry0703/MoneyPrinterTurbo/main/app/controllers/v1/video.py

## 5. Recommended Architecture

### 5.1 Worker Adapter Pattern

Add a dedicated adapter layer:

```text
Nutmeg Daily Content
  -> Production Packet
  -> MoneyPrinterTurbo Task Packet
  -> MoneyPrinterTurbo API Client
  -> Task Status / Download / QC Artifacts
```

The adapter has three responsibilities:

1. Convert Nutmeg's existing public video script into MoneyPrinterTurbo's video request shape.
2. Submit and poll worker tasks through HTTP.
3. Persist worker state without leaking MoneyPrinterTurbo details into `DailyContentService` or the JCZQ domain model.

### 5.2 Module Boundaries

Proposed Python modules:

```text
nutmeg/domain/video_worker.py
nutmeg/services/moneyprinterturbo.py
nutmeg/services/video_worker.py
```

`nutmeg/domain/video_worker.py` defines serializable data objects:

- `MoneyPrinterTurboTaskPacket`
- `MoneyPrinterTurboRequest`
- `MoneyPrinterTurboTaskState`
- `VideoWorkerSubmissionResult`
- `VideoWorkerPollResult`

`nutmeg/services/moneyprinterturbo.py` owns HTTP behavior:

- builds endpoint URLs from `base_url` and `api_prefix`;
- validates that `base_url` is explicit;
- posts `TaskVideoRequest` payloads;
- polls task status;
- downloads final videos from `videos` or `combined_videos` URLs.

`nutmeg/services/video_worker.py` owns Nutmeg orchestration:

- reads production artifacts from a run directory;
- maps each match to an MPT task packet;
- writes `production-mpt` artifacts;
- submits pending tasks when `--confirm` is set;
- polls and downloads completed tasks;
- writes a minimal quality report.

## 6. Artifact Layout

For each match, create a sibling worker folder next to `production-v2`:

```text
<run_dir>/matches/<match_id>/production-mpt/
  mpt-task.json
  request.json
  submit-result.json
  status.json
  videos/
    final-1.mp4
    combined-1.mp4
  quality-report.json
```

At run level, write an aggregate manifest:

```text
<run_dir>/moneyprinterturbo-manifest.json
<run_dir>/moneyprinterturbo-status.json
```

`mpt-task.json` should contain Nutmeg-level intent and provenance. `request.json` should contain the exact MoneyPrinterTurbo HTTP payload. `status.json` should mirror the latest response from the worker. Downloaded videos should be referenced from both per-match and aggregate status files.

## 7. Task Packet Mapping

### 7.1 Nutmeg Inputs

Use existing artifacts first, without requiring new content generation:

- `matches/<match_id>/production-v2/voiceover-script.md`
- `matches/<match_id>/production-v2/content-brief.json`
- `matches/<match_id>/public-script.md`
- `matches/<match_id>/compliance.json`

If `production-v2` is missing, the task packet command may build it through the existing `DailyContentService` flow.

### 7.2 MoneyPrinterTurbo Request Fields

MoneyPrinterTurbo's `VideoParams` supports custom script mode through `video_script`. Nutmeg should send a conservative payload:

```json
{
  "video_subject": "周四001 主队vs客队：赛前关键变量",
  "video_script": "Nutmeg final public script...",
  "video_terms": ["football", "stadium", "training", "match analysis"],
  "video_aspect": "9:16",
  "video_concat_mode": "random",
  "video_transition_mode": "Shuffle",
  "video_clip_duration": 5,
  "video_count": 1,
  "video_source": "pexels",
  "video_language": "zh-CN",
  "voice_name": "zh-CN-XiaoxiaoNeural-Female",
  "voice_volume": 1.0,
  "voice_rate": 1.08,
  "bgm_type": "random",
  "bgm_volume": 0.12,
  "subtitle_enabled": true,
  "subtitle_position": "bottom",
  "font_name": "STHeitiMedium.ttc",
  "text_fore_color": "#FFFFFF",
  "text_background_color": true,
  "font_size": 60,
  "stroke_color": "#000000",
  "stroke_width": 1.5,
  "n_threads": 2,
  "paragraph_number": 1
}
```

Version 1 should prefer `video_script` over `video_subject` generation. `video_subject` is still required as a concise title and fallback descriptor.

### 7.3 Content Rules

- `video_script` must be exactly Nutmeg's sanitized public script.
- The disclaimer from `SHORT_VIDEO_DISCLAIMER` must remain present.
- Forbidden betting terms already handled by Nutmeg must be rechecked before submit.
- Match IDs and source evidence must stay in Nutmeg artifacts, not in public voiceover unless already part of the script.
- `video_terms` should be generic visual keywords, not betting terms or team-logo prompts.

## 8. CLI Design

Add commands with explicit spend/external-worker boundaries:

```bash
nutmeg video-mpt-packet \
  --date today \
  --provider live \
  --output-dir .nutmeg-data/daily-content \
  --format text
```

Builds or reuses the daily content run and writes MPT task packets. No external request is made.

```bash
nutmeg video-mpt-submit \
  --run-dir <run_dir> \
  --confirm \
  --match-id 周四001 \
  --format text
```

Submits pending tasks to MoneyPrinterTurbo. Without `--confirm`, it fails loudly.

```bash
nutmeg video-mpt-poll \
  --run-dir <run_dir> \
  --download \
  --format text
```

Polls task status and optionally downloads completed videos.

Optional diagnostics:

```bash
nutmeg video-mpt-health --format json
```

Checks whether the configured MoneyPrinterTurbo API is reachable and which route prefix works.

## 9. Configuration

Environment variables:

```text
MPT_BASE_URL=http://localhost:8080
MPT_API_PREFIX=/api/v1
MPT_TIMEOUT_SECONDS=60
MPT_DEFAULT_VOICE=zh-CN-XiaoxiaoNeural-Female
MPT_DEFAULT_VIDEO_SOURCE=pexels
MPT_DEFAULT_BGM_VOLUME=0.12
```

Configuration should be read at service construction time, with CLI arguments able to override base URL and prefix for debugging.

## 10. Error Handling

Fail loud and preserve state:

- Missing `run_dir`: raise a validation error with the expected command to generate packets.
- Missing `mpt-task.json`: skip that match and report the missing artifact.
- Compliance risk `HIGH` or `BLOCKED`: do not submit; write status `blocked_by_compliance`.
- Missing disclaimer: do not submit; write status `blocked_by_disclaimer`.
- MoneyPrinterTurbo not reachable: fail the command without deleting local packets.
- HTTP 4xx/5xx: persist request and response body in `submit-result.json` or `status.json`.
- Task response missing `task_id`: mark `failed_submit_contract`.
- Poll response has no final video URLs: keep status as running or review, depending on worker state/progress.
- Download failure: keep remote URL and mark `download_failed` without losing the successful worker status.

## 11. Quality Gates

Version 1 should use lightweight technical and compliance checks:

1. **script_compliance**: forbidden public terms absent and disclaimer present.
2. **worker_contract**: task has `task_id`, status payload is valid JSON, and final URL fields are recognized.
3. **download_integrity**: downloaded files exist and are non-empty.
4. **ffmpeg_decode**: if `ffmpeg` is available, run a decode check against the downloaded video.
5. **artifact_lineage**: each video path links back to `run_id`, `match_id`, request payload, and worker task ID.

Manual visual review remains required before publishing because MPT-selected stock materials may be generic or semantically weak.

## 12. Testing Strategy

Use test doubles; do not require Docker or live MoneyPrinterTurbo in CI.

Unit tests:

- task packet mapping from `ProductionPacketV2` artifacts to `MoneyPrinterTurboRequest`;
- forbidden term and missing-disclaimer submission blocks;
- URL construction with `/api/v1` and empty prefix;
- create-video response parsing;
- poll response parsing for `videos` and `combined_videos`;
- download path generation.

CLI tests:

- `video-mpt-packet` writes expected artifacts;
- `video-mpt-submit` refuses without `--confirm`;
- `video-mpt-submit --confirm` calls a fake client and persists `task_id`;
- `video-mpt-poll --download` records downloaded local video paths.

Optional local smoke test after implementation:

```bash
nutmeg video-mpt-packet --date today --provider sample --output-dir .nutmeg-data/daily-content-smoke
nutmeg video-mpt-submit --run-dir <run_dir> --confirm
nutmeg video-mpt-poll --run-dir <run_dir> --download
ffmpeg -v error -i <downloaded_mp4> -f null -
```

## 13. Rollout Plan

1. Build packet and adapter code with fake-client tests.
2. Add CLI commands with no-submit-by-default safety.
3. Run sample-provider packet generation locally.
4. Start MoneyPrinterTurbo via Docker and submit one sample task manually.
5. Inspect output quality and adjust default voice, clip duration, subtitle style, BGM volume, and visual terms.
6. Decide whether routine daily video jobs should default to MPT or remain an explicit operator action.

## 14. Open Design Choices Fixed for v1

- Integration mode: local Docker MoneyPrinterTurbo service.
- Script ownership: Nutmeg owns the final public script.
- Worker role: MoneyPrinterTurbo handles TTS, stock material selection, subtitles, BGM, and video composition.
- Default shape: vertical 9:16, one output video per match.
- Submit safety: explicit `--confirm` required.

## 15. Future Extensions

- Upload curated local football mood clips to MoneyPrinterTurbo and set `video_source=local` for better sports relevance.
- Add template profiles for batch资讯号, knowledge explainers, and premium match previews.
- Compare MPT outputs with Remotion/Seedance outputs in a review workspace.
- Add a local visual QC pass that samples frames and detects unreadable subtitles, black frames, or off-topic material.
- Add remote worker support once the local Docker path is stable.
