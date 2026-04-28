# Quickstart: Zucai Scheduled Delivery v0

## Dry-run the bundled sample

```bash
uv run nutmeg zucai-auto-run \
  --date 2026-04-26 \
  --slot afternoon \
  --registry-file nutmeg/zucai/samples/scheduled-issues.json \
  --dispatch-telegram \
  --dry-run \
  --format json
```

## Run the revision slot

```bash
uv run nutmeg zucai-auto-run \
  --date 2026-04-26 \
  --slot revision \
  --registry-file nutmeg/zucai/samples/scheduled-issues.json \
  --dispatch-telegram \
  --dry-run \
  --format json
```

## Validate a no-issue day

```bash
uv run nutmeg zucai-auto-run \
  --date 2026-04-27 \
  --slot afternoon \
  --registry-file nutmeg/zucai/samples/scheduled-issues.json \
  --format json
```

Expected status: `skipped_no_issue`.

## Real scheduled send

Review and install the launchd templates in `scripts/launchd/` after confirming paths, chat ids, and Telegram configuration. The templates call `zucai-auto-run` at 16:00 and 18:30 with explicit `--dispatch-telegram --no-dry-run`.
