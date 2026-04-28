# Feature Specification: News Information Provider v0

**Feature Branch**: `039-news-information-provider-v0`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: Continue Nutmeg development by adding a trusted latest-information provider for match news, injuries, fixture status, and lineup-related context.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Normalize local match information (Priority: P1)

As the operator, I want Nutmeg to read local JSON or RSS/Atom-style information items and normalize them into source-attributed match updates, so analysis can include latest context without brittle scraping.

**Why this priority**: The client already has an information panel; it needs a real provider seam before live source integration.

**Independent Test**: Provide deterministic local JSON/RSS files and verify normalized item title, summary, URL, source, reliability, publication time, fixture/team tags, and deduplication.

**Acceptance Scenarios**:

1. **Given** a local information file contains match items, **When** the fixture digest is built, **Then** matching items are normalized with source name, title, summary, URL, publication time, retrieval time, reliability, and tags.
2. **Given** duplicate items share the same URL or title/source, **When** the digest is built, **Then** only the newest representative is kept.
3. **Given** a file is missing, empty, or malformed, **When** the digest is built, **Then** the provider reports unavailable or partial state without fabricating updates.

---

### User Story 2 - Add information digest to match analysis surfaces (Priority: P1)

As a user of the match workspace, I want the information panel to show latest credible updates and caveats, so betting-analysis judgments can account for lineup, injury, and fixture-status context.

**Why this priority**: This directly improves the AI-native betting client’s “latest data and资讯” promise.

**Independent Test**: Build a client match workspace with a local information source and verify the information panel includes summary, latest timestamp, source ledger items, reliability labels, and stale/unavailable warnings.

**Acceptance Scenarios**:

1. **Given** information items match the fixture, **When** `client-match` or `/client/matches/{fixture_id}` is opened, **Then** the information section shows a concise digest and source-attributed items.
2. **Given** only rumor or unverified information is available, **When** the workspace is built, **Then** the section warns that the item is not confirmed and does not raise actionability by itself.
3. **Given** no information source is configured, **When** the workspace is built, **Then** the section says information is unavailable rather than implying no news exists.

---

### User Story 3 - Expose fixture information from CLI (Priority: P2)

As the operator, I want a CLI command for fixture information, so Telegram, Web, and daily workflows can reuse the same source-attributed digest.

**Why this priority**: Nutmeg’s constitution requires CLI-first surfaces for every new workflow.

**Independent Test**: Run `fixture-information` with a local file and verify JSON output is parseable and includes status, summary, items, warnings, and source attribution.

**Acceptance Scenarios**:

1. **Given** a local sources file is supplied, **When** the CLI runs with JSON output, **Then** stdout includes fixture id, status, source count, latest timestamp, summary, items, and warnings.
2. **Given** text mode is used, **When** items exist, **Then** the CLI prints a concise operator-readable digest with reliability labels.
3. **Given** information is unavailable, **When** JSON output is requested, **Then** the CLI exits successfully with `status=unavailable` and warning details.

### Edge Cases

- Local source file is missing, empty, malformed, or has unsupported schema.
- RSS/Atom entries omit publication time, link, or summary.
- Multiple sources repeat the same update with different wording.
- Rumor/unverified items conflict with official source items.
- Item timestamps are old or timezone-less.
- Team names are ambiguous or not present in item text.
- Information provider fails while match workspace still needs to render.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST provide normalized information item and fixture digest entities.
- **FR-002**: Nutmeg MUST read local JSON and RSS/Atom-style files without network access in v0.
- **FR-003**: Information items MUST include source name, title, summary, URL when available, publication time when available, retrieval time, reliability label, fixture ids, teams, and tags.
- **FR-004**: The provider MUST deduplicate items by URL or normalized title/source.
- **FR-005**: Missing, empty, or malformed information sources MUST return unavailable or partial status with warnings.
- **FR-006**: The digest MUST filter by fixture id and supplied team names while preserving unmatched-source warnings.
- **FR-007**: Rumor or unverified items MUST be labeled and MUST NOT be presented as confirmed facts.
- **FR-008**: `ClientService.match_workspace()` MUST use the information provider when configured and keep rendering when unavailable.
- **FR-009**: The CLI MUST expose `fixture-information` with `--fixture-id`, optional `--home-team`, optional `--away-team`, optional `--sources-file`, and `--format text|json`.
- **FR-010**: CLI JSON output MUST remain machine-parseable and include status, summary, items, latest timestamp, source count, and warnings.
- **FR-011**: Documentation MUST explain source reliability, no-scraping v0 scope, and future live provider path.

### Key Entities *(include if feature involves data)*

- **Information Item**: A normalized source-attributed update about a fixture, team, player, injury, lineup, status, or context.
- **Information Digest**: Fixture-level summary containing matching items, status, warnings, latest timestamp, and generated time.
- **Information Source Health**: Source-level availability, item count, warnings, and retrieval timestamp.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A seeded local JSON file produces at least three normalized fixture information items in tests.
- **SC-002**: Duplicate information items are collapsed to one representative in 100% of deduplication tests.
- **SC-003**: Missing or malformed files return a successful unavailable digest with zero fabricated items in 100% of tests.
- **SC-004**: `client-match` includes a real information summary when the local provider is configured.
- **SC-005**: Existing full verification continues to pass.

## Assumptions

- v0 is local-first and no-network; future specs can add HTTP/RSS fetching or paid news APIs.
- JSON is the preferred deterministic fixture for tests; RSS/Atom parsing exists to validate future source shape.
- Reliability labels are advisory and source-driven, not legal verification.
- Information context supports analysis but does not independently create betting recommendations.
