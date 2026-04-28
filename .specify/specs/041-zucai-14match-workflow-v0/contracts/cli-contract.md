# CLI Contract: Traditional Zucai 14-Match Workflow v0

## zucai-report

```bash
uv run nutmeg zucai-report \
  --issue-id 26068 \
  --issue-file nutmeg/zucai/samples/26068-issue.json \
  --odds-file nutmeg/zucai/samples/26068-odds.json \
  --overrides-file nutmeg/zucai/samples/26068-overrides.json \
  --output-dir .nutmeg-data/zucai \
  --pdf \
  --format json
```

### Options

- `--issue-id`: issue id; used to locate bundled sample files when explicit files are omitted.
- `--issue-file`: structured issue JSON.
- `--odds-file`: structured odds JSON.
- `--overrides-file`: optional analyst overrides JSON.
- `--output-dir`: artifact directory, default `.nutmeg-data/zucai`.
- `--pdf`: render PDF in addition to Markdown.
- `--dispatch-telegram`: attach PDF to configured Telegram chat ids.
- `--dry-run/--no-dry-run`: dry-run is default; real Telegram send requires `--dispatch-telegram --no-dry-run`.
- `--format`: `text` or `json`.

### JSON Output

Top-level object contains:

- `issue`: normalized issue metadata and 14 matches.
- `recommendations`: 14 records with `pick`, `primary`, `confidence`, `risk_tier`, `rationale`, and odds evidence.
- `plans`: generated full14 and 任九 plans with stake counts/costs.
- `artifacts`: `markdown_path`, optional `pdf_path`, optional `report_json_path`.
- `dispatch`: status object (`skipped`, `dry_run`, `sent`, `failed`, `config_missing`).
- `warnings` and `sources`.

## zucai-grade

```bash
uv run nutmeg zucai-grade \
  --report-file .nutmeg-data/zucai/zucai-26068-report.json \
  --outcomes-file nutmeg/zucai/samples/26068-outcomes.json \
  --format json
```

### JSON Output

- `issue_id`
- `match_results`: 14 per-match records with selected pick, result, and hit/unresolved flag.
- `plan_results`: plan-level selected count, hit count, and covered boolean.
- `warnings`

## Failure Semantics

- Invalid issue shape exits non-zero with a clear message.
- Missing odds are warnings, not fabricated confidence.
- Invalid overrides are warnings and are not applied.
- PDF errors do not prevent JSON/Markdown output.
- Telegram errors do not delete or hide generated artifacts.
