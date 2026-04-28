# CLI Contract: Zucai Scheduled Delivery v0

## zucai-auto-run

```bash
uv run nutmeg zucai-auto-run \
  --date 2026-04-26 \
  --slot afternoon \
  --registry-file nutmeg/zucai/samples/scheduled-issues.json \
  --output-dir .nutmeg-data/zucai/scheduled \
  --run-record-file .nutmeg-data/zucai/scheduled-runs.json \
  --dispatch-telegram \
  --dry-run \
  --format json
```

### Options

- `--date`: `YYYY-MM-DD` or `today`; default `today`.
- `--slot`: `afternoon` or `revision`; required by scheduled jobs.
- `--registry-file`: Local issue registry JSON; default `.nutmeg-data/zucai/issues.json`.
- `--output-dir`: Root directory for slot artifacts; default `.nutmeg-data/zucai/scheduled`.
- `--run-record-file`: JSON run ledger; default `.nutmeg-data/zucai/scheduled-runs.json`.
- `--dispatch-telegram`: Enable PDF document dispatch.
- `--dry-run/--no-dry-run`: Dry-run is default. Real send requires `--dispatch-telegram --no-dry-run` and configured chat ids.
- `--force`: Regenerate and resend even if the same date/slot/issue already has a completed run.
- `--quiet`: Print nothing for skipped no-issue runs in text mode.
- `--format`: `text` or `json`.

### JSON Result Shape

```json
{
  "run_date": "2026-04-26",
  "slot": "afternoon",
  "slot_label": "16:00首版分析",
  "issue_id": "26068",
  "status": "dry_run",
  "generated_at": "2026-04-26T08:00:00+00:00",
  "skipped_reason": null,
  "artifacts": {
    "markdown_path": ".nutmeg-data/zucai/scheduled/26068/2026-04-26-afternoon/zucai-26068-report.md",
    "pdf_path": ".nutmeg-data/zucai/scheduled/26068/2026-04-26-afternoon/zucai-26068-report.pdf",
    "report_json_path": ".nutmeg-data/zucai/scheduled/26068/2026-04-26-afternoon/zucai-26068-report.json"
  },
  "dispatch": {
    "status": "dry_run",
    "caption": "Nutmeg 足彩第26068期14场报告 - 16:00首版分析（分析辅助，不保证命中）"
  },
  "warnings": []
}
```

No-issue result:

```json
{
  "run_date": "2026-04-27",
  "slot": "afternoon",
  "slot_label": "16:00首版分析",
  "issue_id": null,
  "status": "skipped_no_issue",
  "skipped_reason": "no active traditional Zucai issue for run date",
  "artifacts": {},
  "dispatch": {"status": "skipped"},
  "warnings": []
}
```
