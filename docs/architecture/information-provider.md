# Information Provider

The information provider is Nutmeg's source-attributed seam for latest match
context: team news, lineup notes, fixture-status updates, injury snippets, and
source-led rumors. It is built for betting-analysis assistance, so it preserves
attribution and reliability labels instead of turning every update into a
confident betting fact.

## Scope

Implemented local-first and live-cache scope:

- reads deterministic local JSON files and RSS/Atom-style XML files;
- bundles item and manifest samples at `nutmeg/information/samples/`;
- supports an explicit JSON source manifest with local files and remote RSS/JSON
  URLs;
- fetches remote URLs only when the operator passes an explicit live-fetch flag;
- caches remote responses by URL hash under a local cache directory;
- uses fresh cache without network access and stale cache only as a labeled
  partial fallback after live fetch failure;
- normalizes updates into `InformationItem` records and fixture-level
  `FixtureInformationDigest` payloads;
- exposes the digest through `nutmeg fixture-information` and optional
  `client-match` information manifest flags;
- does not scrape arbitrary webpages, use hidden source discovery, or add
  authenticated/paid API coupling in v0.

## Data Flow

1. Without a manifest, `LocalInformationProvider` chooses an explicit
   `--sources-file` or the bundled path `{fixture_id}-information.json`.
2. With a manifest, `LiveInformationProvider` loads enabled source definitions,
   validates local paths and remote URLs, and records warnings for malformed
   entries.
3. Local JSON/RSS content is parsed directly. Remote content is read from fresh
   cache unless `--live-fetch` is present.
4. Live remote fetch uses bounded HTTP GET with timeout and max-size guards. A
   successful response is cached with URL, content type, status, fetched time,
   and body.
5. If live fetch fails and a stale cache exists, the provider parses stale cache
   and reports partial/stale warnings. If no cache exists, it reports unavailable
   source health and returns no fabricated items.
6. `FixtureInformationService.build_digest()` filters by fixture id and optional
   home/away team names, deduplicates by URL or normalized `source:title`, and
   keeps rumor/unverified warnings visible.
7. `ClientService.match_workspace()` passes fixture team context into the
   provider and renders the result in CLI JSON and Web/PWA match pages.

## Source Manifest

Example:

```json
{
  "cache_ttl_seconds": 900,
  "timeout_seconds": 3,
  "max_bytes": 262144,
  "sources": [
    {
      "source_name": "Bundled local sample",
      "kind": "local_json",
      "path": "nutmeg/information/samples/epl-001-information.json",
      "fixture_ids": ["epl-001"],
      "teams": ["Arsenal", "Tottenham Hotspur"],
      "reliability": "credible",
      "tags": ["team_news"]
    },
    {
      "source_name": "Trusted club RSS",
      "kind": "remote_rss",
      "url": "https://example.test/club-feed.xml",
      "reliability": "official",
      "teams": ["Arsenal"],
      "tags": ["official", "team_news"]
    }
  ]
}
```

Supported source kinds are `local_json`, `local_rss`, `remote_json`, and
`remote_rss`. Disabled or malformed entries create warnings and do not block
valid sources.

Source-level `fixture_ids` and `teams` are defaults for items that do not carry
item-level fixture/team tags. They do not override explicit item tags, which
prevents an unrelated item from being pulled into the wrong fixture.

## Reliability Labels

- `official`: club, league, competition, or primary-source update.
- `credible`: trusted media/data source, still not official confirmation.
- `rumor`: plausible but unconfirmed report.
- `unverified`: source did not supply enough confirmation metadata.

Rumor and unverified items remain visible because they can affect operator
awareness, but the digest adds a warning and the client must not raise
actionability from information alone.

## CLI Contract

Local sample mode:

```bash
uv run nutmeg fixture-information \
  --fixture-id epl-001 \
  --home-team Arsenal \
  --away-team "Tottenham Hotspur" \
  --format json
```

Manifest cache/no-network mode:

```bash
uv run nutmeg fixture-information \
  --fixture-id epl-001 \
  --sources-config nutmeg/information/samples/epl-001-sources.json \
  --format json
```

Opt-in live fetch:

```bash
uv run nutmeg fixture-information \
  --fixture-id epl-001 \
  --sources-config config/information-sources.json \
  --cache-dir .nutmeg-data/information-cache \
  --live-fetch \
  --format json
```

Client-match override:

```bash
uv run nutmeg client-match \
  --fixture-id epl-001 \
  --information-sources-config config/information-sources.json \
  --information-cache-dir .nutmeg-data/information-cache \
  --live-information-fetch \
  --format json
```

The JSON response stays machine-parseable even when manifests, files, remote
feeds, or cache entries are missing or malformed. Those cases return
`status=unavailable` or `status=partial`, zero fabricated remote items, and
warning details.

## Client Behavior

The match workspace shows:

- concise digest summary;
- source count and latest publication timestamp when available;
- item title, source name, and reliability label;
- warnings for rumor/unverified, unavailable information, and stale cache
  fallback.

This keeps latest context visible beside market, player, and tactical evidence
without making the UI look like a bet-execution surface.

## Future Authenticated Provider Path

Future specs can add source-specific auth, paid sports-news APIs, stronger
rate-limit ledgers, persistent source health, and scheduled refresh. New live
providers must return the same normalized digest contract, keep source
attribution, avoid secret leakage, and fail closed with warnings when source
health is poor.
