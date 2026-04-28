# CLI Contract: Zucai Odds Source v0

```bash
uv run nutmeg zucai-odds-sync \
  --source-file nutmeg/zucai/samples/26068-odds-source-afternoon.html \
  --issue-id 26068 \
  --slot afternoon \
  --captured-at "2026-04-26 16:00 CST" \
  --output-dir .nutmeg-data/zucai \
  --registry-file .nutmeg-data/zucai/issues.json \
  --format json
```

Options:

- `--source-file`: Local HTML/text odds table.
- `--source-url`: Trusted odds URL. Requires `--live-fetch`.
- `--live-fetch`: Explicitly allow bounded HTTP fetch.
- `--issue-id`: Required if the source does not include a clear issue id.
- `--slot`: `afternoon` or `revision`.
- `--captured-at`: Capture timestamp; source metadata can override if present.
- `--source-label`: Source attribution label.
- `--output-dir`: Directory for odds snapshots.
- `--registry-file`: Registry consumed by `zucai-auto-run`.
- `--format`: `text` or `json`.
