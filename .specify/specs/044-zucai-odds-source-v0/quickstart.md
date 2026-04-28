# Quickstart: Zucai Odds Source v0

```bash
uv run nutmeg zucai-source-sync --source-file nutmeg/zucai/samples/26068-source-notice.html --date 2026-04-26 --output-dir .nutmeg-data/zucai/odds-smoke --registry-file .nutmeg-data/zucai/odds-smoke/issues.json --format json
uv run nutmeg zucai-odds-sync --source-file nutmeg/zucai/samples/26068-odds-source-afternoon.html --issue-id 26068 --slot afternoon --captured-at "2026-04-26 16:00 CST" --output-dir .nutmeg-data/zucai/odds-smoke --registry-file .nutmeg-data/zucai/odds-smoke/issues.json --format json
uv run nutmeg zucai-odds-sync --source-file nutmeg/zucai/samples/26068-odds-source-revision.html --issue-id 26068 --slot revision --captured-at "2026-04-26 18:30 CST" --output-dir .nutmeg-data/zucai/odds-smoke --registry-file .nutmeg-data/zucai/odds-smoke/issues.json --format json
uv run nutmeg zucai-auto-run --date 2026-04-26 --slot revision --registry-file .nutmeg-data/zucai/odds-smoke/issues.json --output-dir .nutmeg-data/zucai/odds-smoke/scheduled --run-record-file .nutmeg-data/zucai/odds-smoke/scheduled-runs.json --dispatch-telegram --dry-run --format json
```
