# Video Production v2

Nutmeg v2 short-video production uses Python for content packets, Seedance for mood shots, Remotion for deterministic tactical graphics, and FFmpeg for final verification.

## Local No-Spend Smoke

```bash
nutmeg video-production-packet --date 2026-04-26 --provider sample --output-dir .nutmeg-data/daily-content-smoke --format json
npm --prefix video/remotion install
npm --prefix video/remotion run render -- "$(pwd)/.nutmeg-data/video-production-smoke/remotion-sample.mp4" --props "$(pwd)/tests/fixtures/video_production/sample_v2_timeline.json"
ffmpeg -v error -i .nutmeg-data/video-production-smoke/remotion-sample.mp4 -f null -
```

## MoneyPrinterTurbo Worker Path

Nutmeg can also use a local Docker MoneyPrinterTurbo service as a faceless-video worker. In this path, Nutmeg still owns match selection, public scripts, disclaimers, and compliance checks. MoneyPrinterTurbo handles TTS, stock material selection, subtitles, BGM, and final video assembly.

Start MoneyPrinterTurbo separately:

```bash
cd MoneyPrinterTurbo
docker compose up
```

Default API configuration:

```bash
export MPT_BASE_URL=http://localhost:8080
export MPT_API_PREFIX=/api/v1
```

If the local deployment exposes unprefixed routes, use:

```bash
export MPT_API_PREFIX=
```

Build local worker packets without submitting external work:

```bash
nutmeg video-mpt-packet --date 2026-04-26 --provider sample --output-dir .nutmeg-data/daily-content-smoke --format json
```

Submit only after review:

```bash
nutmeg video-mpt-submit --run-dir .nutmeg-data/daily-content-smoke/20260426/run-120000 --confirm --format json
```

Poll and download completed videos:

```bash
nutmeg video-mpt-poll --run-dir .nutmeg-data/daily-content-smoke/20260426/run-120000 --download --format json
```

The run directory records `moneyprinterturbo-manifest.json`, `moneyprinterturbo-status.json`, and per-match `production-mpt` folders. Manual visual review remains required before publishing because stock footage can be generic or off-topic.

## Provider Spend Boundary

Seedance mood-shot submission remains behind explicit confirmation. Do not submit provider tasks from tests.

## Ownership Split

- Python Content Brain: hook, contradiction, tactical beats, scripts, quality report.
- Seedance: no-text mood shots only; no captions, logos, numbers, scoreboards, or tactical UI.
- Remotion: all text, captions, tactical maps, timing, and deterministic broadcast graphics.
- FFmpeg: muxing, duration checks, and decode verification before upload.
