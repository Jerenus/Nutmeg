# Quickstart: Live Information Provider v0

Create a manifest:

```json
{
  "cache_ttl_seconds": 900,
  "sources": [
    {
      "source_name": "Bundled sample",
      "kind": "local_json",
      "path": "nutmeg/information/samples/epl-001-information.json",
      "reliability": "credible",
      "fixture_ids": ["epl-001"],
      "teams": ["Arsenal", "Tottenham Hotspur"],
      "tags": ["team_news"]
    },
    {
      "source_name": "Trusted club RSS",
      "kind": "remote_rss",
      "url": "https://example.test/rss.xml",
      "reliability": "official",
      "teams": ["Arsenal"],
      "tags": ["official", "team_news"]
    }
  ]
}
```

Use cache/no-network mode:

```bash
uv run nutmeg fixture-information \
  --fixture-id epl-001 \
  --sources-config config/information-sources.example.json \
  --format json
```

Opt into live fetching:

```bash
uv run nutmeg fixture-information \
  --fixture-id epl-001 \
  --sources-config config/information-sources.example.json \
  --live-fetch \
  --format json
```

Use the same provider in a client match workspace:

```bash
uv run nutmeg client-match \
  --fixture-id epl-001 \
  --information-sources-config config/information-sources.example.json \
  --live-information-fetch \
  --format json
```

Expected behavior:

- No remote URL is contacted unless the live-fetch flag is present.
- Fresh cache can supply remote feed content without network.
- Failed live fetch can use stale cache only with partial/stale warnings.
- Rumor/unverified source labels remain visible in the digest and client panel.
