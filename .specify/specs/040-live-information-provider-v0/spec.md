# Feature Specification: Live Information Provider v0

**Feature Branch**: `040-live-information-provider-v0`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: Continue Nutmeg development by extending the local information digest into an opt-in live/cache provider for latest match news and RSS/HTTP feeds.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure trusted information sources (Priority: P1)

As the operator, I want to define explicit trusted local and remote information sources in a manifest, so Nutmeg can refresh latest context only from sources I have approved.

**Why this priority**: Latest information must be source-controlled. A manifest prevents arbitrary scraping and makes future subscription/client behavior auditable.

**Independent Test**: Provide a deterministic manifest with one local file and one remote feed definition, then verify Nutmeg validates enabled sources, reliability defaults, tags, fixture/team hints, and warnings for disabled or invalid entries.

**Acceptance Scenarios**:

1. **Given** a source manifest lists local and remote sources, **When** the manifest is loaded, **Then** enabled sources are normalized with source name, source kind, reliability, URL/path, tags, teams, and fetch policy.
2. **Given** a manifest contains disabled or malformed source entries, **When** the digest is built, **Then** disabled entries are ignored and malformed entries create warnings without stopping valid sources.
3. **Given** no manifest is supplied, **When** `fixture-information` runs, **Then** the existing 039 local sample behavior still works.

---

### User Story 2 - Refresh remote feeds safely with cache fallback (Priority: P1)

As the operator, I want Nutmeg to fetch explicit RSS/HTTP source URLs only when I opt in, cache the response, and fall back to cached content if live fetch fails, so latest information improves without making daily workflows fragile.

**Why this priority**: This is the core bridge from local fixtures to latest information while preserving deterministic testing and responsible source handling.

**Independent Test**: Inject a fake HTTP fetcher that returns JSON/RSS bodies, errors, timeouts, and oversized responses; verify cache writes, cache hits, stale fallback, warnings, source health, and no-network default behavior.

**Acceptance Scenarios**:

1. **Given** a remote RSS source and `--live-fetch`, **When** the fetch succeeds, **Then** Nutmeg normalizes items, writes a cache entry, and reports source health as complete.
2. **Given** a fresh cache exists and live fetch is not requested, **When** the digest is built, **Then** Nutmeg reads cached content without network access and marks the source as cached.
3. **Given** a live fetch fails but a stale cache exists, **When** the digest is built, **Then** Nutmeg uses stale cached items, reports partial status/warnings, and does not fabricate freshness.
4. **Given** no cache exists and live fetch is disabled or fails, **When** the digest is built, **Then** Nutmeg returns unavailable/partial source health with zero fabricated remote items.

---

### User Story 3 - Surface live information through operator and client commands (Priority: P2)

As the operator, I want CLI and client match commands to accept an explicit information manifest and cache controls, so the same latest-information digest can be used in automation, Telegram routing, and the AI-native client workspace.

**Why this priority**: Nutmeg is CLI-first and bot-ready; the client should reuse the same provider seam rather than duplicating refresh logic.

**Independent Test**: Run CLI commands with a manifest, fake/cache-backed sources, and JSON output; verify machine-parseable status, source health, items, cache metadata, and client workspace information payload.

**Acceptance Scenarios**:

1. **Given** a manifest and live-fetch flag are supplied to `fixture-information`, **When** JSON output is requested, **Then** the digest includes items, source health, cache status, warnings, and latest timestamp.
2. **Given** an explicit manifest is supplied to `client-match`, **When** the workspace is built, **Then** its information panel consumes the same digest contract.
3. **Given** remote information is unavailable, **When** JSON output is requested, **Then** commands exit successfully with clear unavailable/partial warnings.

### Edge Cases

- Manifest path is missing, empty, malformed, or contains unsupported source kinds.
- Remote URL is invalid, disabled, too large, times out, or returns non-200 status.
- Remote response has malformed JSON/XML or a misleading content type.
- Cache is fresh, stale, missing, or malformed.
- Local and remote sources duplicate the same item by URL or title/source.
- Rumor/unverified remote items are present without official confirmation.
- Live fetch is accidentally omitted; system must not contact network by default.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST support an explicit information source manifest containing local file sources and remote URL sources.
- **FR-002**: Manifest sources MUST include source name, kind, reliability label, enabled state, URL or path, optional tags, optional teams, and optional fixture ids.
- **FR-003**: Remote fetching MUST be opt-in; default digest builds MUST NOT contact network URLs.
- **FR-004**: Remote fetches MUST enforce timeout and response-size limits.
- **FR-005**: Remote responses MUST be cached locally with fetched timestamp, source URL, content type, status, and body.
- **FR-006**: Fresh cache entries MUST be usable without network access.
- **FR-007**: Stale cache entries MAY be used when live fetch fails, but the digest MUST report stale/partial warnings.
- **FR-008**: Missing, malformed, timed-out, oversized, or failed remote sources MUST create source health warnings without fabricating items.
- **FR-009**: Remote JSON and RSS/Atom content MUST normalize into the existing `InformationItem`/`FixtureInformationDigest` contract.
- **FR-010**: Deduplication, fixture/team filtering, reliability labels, and rumor/unverified warnings from 039 MUST continue to apply across local and remote sources.
- **FR-011**: `fixture-information` MUST expose manifest, cache, TTL, timeout, size-limit, and live-fetch controls while keeping JSON output parseable.
- **FR-012**: `client-match` MUST be able to use an explicit information manifest for its information payload without changing user-state isolation.
- **FR-013**: Documentation MUST explain no-scraping scope, opt-in live fetch, cache semantics, source reliability, and future authenticated provider path.

### Key Entities *(include if feature involves data)*

- **Information Source Manifest**: Operator-approved list of local and remote information sources plus defaults.
- **Information Source Definition**: One manifest source with kind, URL/path, reliability, tags, teams, fixture ids, and fetch policy.
- **Information Cache Entry**: Stored remote response body and metadata used for fresh cache hits or stale fallback.
- **Live Information Provider**: Provider that merges local sources, remote source cache/fetch results, source health, and warnings into the existing digest contract.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Remote fetch tests prove zero network calls occur unless live fetch is explicitly enabled.
- **SC-002**: Fresh cache and stale fallback behavior pass 100% of deterministic cache tests.
- **SC-003**: Manifest-backed `fixture-information --format json` returns parseable JSON for success, partial, and unavailable scenarios.
- **SC-004**: Client match workspace can consume a manifest-backed information digest in tests.
- **SC-005**: Existing 039 local sample behavior remains backward-compatible.
- **SC-006**: Existing full verification continues to pass.

## Assumptions

- v0 supports unauthenticated HTTP GET only; authenticated APIs, API keys, and vendor-specific rate limits are future specs.
- v0 accepts explicit RSS/Atom or JSON response bodies, not arbitrary web-page scraping.
- Cache files are local operator state and can be regenerated.
- The existing 039 information domain remains the public digest contract.
