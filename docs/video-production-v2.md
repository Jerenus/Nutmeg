# Video Production v2

Nutmeg v2 short-video production uses Python for content packets, Seedance for mood shots, Remotion for deterministic tactical graphics, and FFmpeg for final verification.

## Local No-Spend Smoke

```bash
nutmeg video-production-packet --date 2026-04-26 --provider sample --output-dir .nutmeg-data/daily-content-smoke --format json
npm --prefix video/remotion install
npm --prefix video/remotion run render -- "$(pwd)/.nutmeg-data/video-production-smoke/remotion-sample.mp4" --props "$(pwd)/tests/fixtures/video_production/sample_v2_timeline.json"
ffmpeg -v error -i .nutmeg-data/video-production-smoke/remotion-sample.mp4 -f null -
```

## Provider Spend Boundary

Seedance mood-shot submission remains behind explicit confirmation. Do not submit provider tasks from tests.

## Ownership Split

- Python Content Brain: hook, contradiction, tactical beats, scripts, quality report.
- Seedance: no-text mood shots only; no captions, logos, numbers, scoreboards, or tactical UI.
- Remotion: all text, captions, tactical maps, timing, and deterministic broadcast graphics.
- FFmpeg: muxing, duration checks, and decode verification before upload.
