# CLI Contract: Zucai Source Parser v0

## zucai-source-sync

```bash
uv run nutmeg zucai-source-sync \
  --source-file nutmeg/zucai/samples/26068-source-notice.html \
  --date 2026-04-26 \
  --output-dir .nutmeg-data/zucai \
  --registry-file .nutmeg-data/zucai/issues.json \
  --format json
```

### Options

- `--source-file`: Local HTML/text source notice.
- `--source-url`: Trusted source URL. Requires `--live-fetch`.
- `--live-fetch`: Explicitly allow bounded HTTP fetch for `--source-url`.
- `--date`: `YYYY-MM-DD` or `today`; default `today`; used to report active issue ids.
- `--source-label`: Source attribution label; default `Zucai schedule source`.
- `--output-dir`: Directory where `*-issue.json` snapshots are written; default `.nutmeg-data/zucai`.
- `--registry-file`: Registry JSON consumed by `zucai-auto-run`; default `.nutmeg-data/zucai/issues.json`.
- `--timeout-seconds`: HTTP timeout for live fetch; default 5 seconds.
- `--max-bytes`: Maximum response bytes retained from live fetch; default 524288.
- `--format`: `text` or `json`.

### JSON Result Shape

```json
{
  "generated_at": "2026-04-26T08:00:00+00:00",
  "run_date": "2026-04-26",
  "source_label": "Zucai schedule source",
  "source_url": null,
  "source_path": "nutmeg/zucai/samples/26068-source-notice.html",
  "parsed_count": 1,
  "written_issue_paths": {"26068": ".nutmeg-data/zucai/26068-issue.json"},
  "registry_path": ".nutmeg-data/zucai/issues.json",
  "active_issue_ids": ["26068"],
  "warnings": []
}
```
