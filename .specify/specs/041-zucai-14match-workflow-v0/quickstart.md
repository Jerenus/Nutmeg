# Quickstart: Traditional Zucai 14-Match Workflow v0

Generate the bundled issue 26068 report:

```bash
uv run nutmeg zucai-report --issue-id 26068 --pdf --format json
```

Generate from explicit files:

```bash
uv run nutmeg zucai-report \
  --issue-file nutmeg/zucai/samples/26068-issue.json \
  --odds-file nutmeg/zucai/samples/26068-odds.json \
  --overrides-file nutmeg/zucai/samples/26068-overrides.json \
  --output-dir .nutmeg-data/zucai \
  --pdf
```

Dry-run Telegram PDF delivery:

```bash
uv run nutmeg zucai-report --issue-id 26068 --pdf --dispatch-telegram --dry-run --format json
```

Real delivery, only when explicitly intended:

```bash
uv run nutmeg zucai-report --issue-id 26068 --pdf --dispatch-telegram --no-dry-run --format json
```

Grade after results are known:

```bash
uv run nutmeg zucai-grade \
  --report-file .nutmeg-data/zucai/zucai-26068-report.json \
  --outcomes-file nutmeg/zucai/samples/26068-outcomes.json \
  --format json
```

Expected behavior:

- Report generation never places bets.
- Missing odds or invalid overrides produce warnings.
- Markdown is always written; PDF is written when requested.
- Telegram is dry-run unless `--no-dry-run` is present.
