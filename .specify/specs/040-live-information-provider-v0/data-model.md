# Data Model: Live Information Provider v0

## InformationSourceDefinition

- `source_name`: human-readable source label.
- `kind`: `local_json`, `local_rss`, `remote_json`, or `remote_rss`.
- `enabled`: whether the source should be considered.
- `path`: local file path for local sources.
- `url`: remote URL for remote sources.
- `reliability`: `official`, `credible`, `rumor`, or `unverified` default applied when source items omit reliability.
- `fixture_ids`: optional fixture ids tagged at source level.
- `teams`: optional team names tagged at source level.
- `tags`: optional context tags applied to source items.
- `cache_ttl_seconds`: optional per-source cache freshness threshold.
- `timeout_seconds`: optional per-source HTTP timeout.
- `max_bytes`: optional per-source response size cap.

Validation:

- Disabled sources are ignored.
- Local sources require `path`; remote sources require `url`.
- Unsupported kinds create manifest warnings and do not stop valid sources.
- Reliability defaults to `unverified` when unknown.

## InformationCacheEntry

- `cache_key`: stable hash of source URL.
- `url`: remote source URL.
- `content_type`: response content type when available.
- `status_code`: response status when available.
- `fetched_at`: timestamp of successful fetch.
- `body`: cached response body.
- `warnings`: cache/fetch warnings.

Validation:

- Freshness is computed from `fetched_at` and TTL.
- Malformed cache entries are ignored with warnings.
- Stale cache fallback must be reported as partial/stale.

## LiveInformationProvider

- `manifest_path`
- `cache_dir`
- `live_fetch`
- `default_cache_ttl_seconds`
- `default_timeout_seconds`
- `default_max_bytes`
- `fetcher`

Relationships:

- Loads many `InformationSourceDefinition` objects.
- Reads/writes many `InformationCacheEntry` files.
- Emits existing `InformationItem` and `InformationSourceHealth` records.
