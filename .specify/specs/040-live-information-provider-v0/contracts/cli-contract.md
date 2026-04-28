# CLI Contract: Live Information Provider v0

## fixture-information

```bash
uv run nutmeg fixture-information \
  --fixture-id epl-001 \
  --home-team Arsenal \
  --away-team "Tottenham Hotspur" \
  --sources-config config/information-sources.example.json \
  --cache-dir .nutmeg-data/information-cache \
  --cache-ttl-seconds 900 \
  --timeout-seconds 3 \
  --max-bytes 262144 \
  [--live-fetch] \
  --format json
```

### JSON Output Additions

The existing 039 digest output remains the top-level contract. Source health entries may include warnings such as:

- `remote fetch disabled and no fresh cache`
- `using fresh cache`
- `using stale cache after fetch failure`
- `remote response exceeded max bytes`
- `remote fetch failed: ...`

## client-match

```bash
uv run nutmeg client-match \
  --fixture-id epl-001 \
  --information-sources-config config/information-sources.example.json \
  --information-cache-dir .nutmeg-data/information-cache \
  [--live-information-fetch] \
  --format json
```

The `information` object in the client workspace reuses the same digest summary, status, items, latest timestamp, source count, and warnings.

## Failure Semantics

- Live fetch is off by default.
- Missing/invalid manifest returns exit code 0 with warnings and no fabricated remote items.
- Failed remote fetch with no cache returns unavailable/partial source health.
- Failed remote fetch with stale cache may return items, but source health and digest warnings must identify stale fallback.
