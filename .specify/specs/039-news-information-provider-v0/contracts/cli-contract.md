# CLI Contract: fixture-information

## Command

```bash
uv run nutmeg fixture-information \
  --fixture-id epl-001 \
  [--home-team Arsenal] \
  [--away-team "Tottenham Hotspur"] \
  [--sources-file path/to/information.json] \
  [--format text|json]
```

## JSON Output Shape

```json
{
  "fixture_id": "epl-001",
  "status": "complete",
  "summary": "3 relevant updates from 2 sources. Latest: ...",
  "source_count": 2,
  "latest_published_at": "2026-04-26T10:00:00+00:00",
  "items": [
    {
      "item_id": "official-lineup-note",
      "source_name": "Club official",
      "source_type": "json",
      "title": "Arsenal fullback returns to training",
      "summary": "...",
      "url": "https://example.test/news",
      "published_at": "2026-04-26T10:00:00+00:00",
      "retrieved_at": "2026-04-26T10:05:00+00:00",
      "reliability": "official",
      "fixture_ids": ["epl-001"],
      "teams": ["Arsenal"],
      "tags": ["injury"]
    }
  ],
  "warnings": [],
  "generated_at": "2026-04-26T10:05:00+00:00"
}
```

## Failure Semantics

- Missing or empty source data returns exit code 0 with `status=unavailable` and empty `items`.
- Malformed local data returns exit code 0 with `status=unavailable` or `partial` plus warnings.
- JSON stdout must remain parseable.
