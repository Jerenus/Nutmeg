# Live Information Provider v0 Design

Date: 2026-04-26

## Context

`039-news-information-provider-v0` added a local-first match information digest and proved that the AI-native client can render source-attributed information. The next product gap is safe freshness: operators need explicit RSS/HTTP sources and cache-backed refresh behavior without brittle scraping or network-dependent tests.

## Recommended Approach

Use a source manifest plus cache-backed HTTP/RSS provider. The manifest lists allowed local files and remote feed endpoints with source name, reliability, tags, and optional team hints. Remote fetching is opt-in through a CLI flag; cached content can be reused without network access. Tests inject a fake fetcher, so the feature remains deterministic.

## Alternatives Considered

- Direct web scraping: rejected because it is brittle, legally ambiguous, and conflicts with source attribution discipline.
- Paid sports/news API integration now: rejected because the digest contract should stabilize before adding vendor-specific auth/rate-limit behavior.
- Local files only: rejected because it does not advance the user's latest-information requirement beyond 039.

## Scope

- Add a JSON source manifest contract for local files and remote feed URLs.
- Add cache metadata with fetched timestamp, URL hash, status, and warnings.
- Add opt-in live HTTP fetch with timeout, size cap, and stale-cache fallback.
- Parse remote JSON or RSS/Atom content through the same normalized information item contract as 039.
- Extend `fixture-information` with manifest/cache/live-fetch flags.
- Optionally let `client-match` use an explicit manifest for the information provider so the match workspace can demonstrate refreshed information without global settings.

## Guardrails

- No scraping arbitrary webpages.
- No live network fetch unless the user explicitly opts in.
- No secrets or auth headers in v0.
- Failed live fetches return warnings and stale/unavailable state instead of fabricated news.
- Rumor/unverified labels remain visible and do not independently raise betting actionability.

## Test Strategy

- RED/GREEN service tests for manifest parsing, fake HTTP fetch, cache hits, stale fallback, timeout/error handling, and remote JSON/RSS normalization.
- CLI tests for parseable JSON, cache/live flags, and unavailable states.
- Client-match test for explicit manifest injection into the information panel.
- Full `scripts/verify.sh`, ruff, compileall, wheel package-data, and graph refresh before verification.
