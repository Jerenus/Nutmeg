# Quickstart: News Information Provider v0

Use bundled deterministic sample:

```bash
uv run nutmeg fixture-information --fixture-id epl-001 --home-team Arsenal --away-team "Tottenham Hotspur" --format json
```

Use an explicit local source file:

```bash
uv run nutmeg fixture-information \
  --fixture-id epl-001 \
  --home-team Arsenal \
  --away-team "Tottenham Hotspur" \
  --sources-file nutmeg/information/samples/epl-001-information.json \
  --format json
```

Check client integration:

```bash
uv run nutmeg client-match --fixture-id epl-001 --format json
```

Expected behavior:

- Local sample data produces source-attributed official/credible/rumor items.
- Missing data reports `status=unavailable` and does not fabricate updates.
- Client workspace information payload uses the same digest summary.
