# Quickstart: Zucai Source Parser v0

## Parse bundled sample into a temp registry

```bash
uv run nutmeg zucai-source-sync \
  --source-file nutmeg/zucai/samples/26068-source-notice.html \
  --date 2026-04-26 \
  --output-dir .nutmeg-data/zucai/source-smoke \
  --registry-file .nutmeg-data/zucai/source-smoke/issues.json \
  --format json
```

## Use generated registry with scheduled run

```bash
uv run nutmeg zucai-auto-run \
  --date 2026-04-26 \
  --slot afternoon \
  --registry-file .nutmeg-data/zucai/source-smoke/issues.json \
  --output-dir .nutmeg-data/zucai/source-smoke/scheduled \
  --run-record-file .nutmeg-data/zucai/source-smoke/scheduled-runs.json \
  --dispatch-telegram \
  --dry-run \
  --format json
```

## Safe live fetch

```bash
uv run nutmeg zucai-source-sync \
  --source-url https://example.com/trusted-zucai-schedule.html \
  --live-fetch \
  --date today \
  --format json
```

Without `--live-fetch`, URL mode exits with a validation error and makes no request.
