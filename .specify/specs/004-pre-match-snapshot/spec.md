# Feature Specification: Pre-Match Snapshot Completion Sprint 1 Slice

**Feature Branch**: `004-pre-match-snapshot`  
**Created**: 2026-04-24  
**Status**: Verified
**Input**: User description: "Continue Sprint 1 by adding Transfermarkt market value and injuries, then lineups / probable lineups, then perform a fuller Sprint 1 acceptance pass."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Add squad health and value context to the fixture snapshot (Priority: P1)

As the Nutmeg operator, I want the fixture snapshot to include team market-value context and current injury availability so the pre-match view captures squad quality and missing-player risk.

**Why this priority**: `Nutmeg-DESIGN-v0.3.md` names Transfermarkt-backed value and injury context as part of the Sprint 1 data puzzle.

**Independent Test**: Run `nutmeg fixture-snapshot --fixture-id <id> --format json` with provider mocks and verify that home/away blocks include market-value and injury sections.

**Acceptance Scenarios**:

1. **Given** a fixture with mapped teams, **When** the snapshot is built, **Then** each team block includes market-value context sourced from Transfermarkt data.
2. **Given** current injury data exists for the fixture teams, **When** the snapshot is built, **Then** each team block includes structured injury availability entries.

---

### User Story 2 - Add lineups or probable lineups to the snapshot (Priority: P1)

As the Nutmeg operator, I want each snapshot to include either confirmed lineups or a probable-lineup fallback so the pre-match context reflects likely on-pitch personnel.

**Why this priority**: The Sprint 1 deliverable explicitly expands from schedule-only data into usable match context.

**Independent Test**: Mock a confirmed lineup provider response and a fallback path; verify the snapshot distinguishes `confirmed` from `probable`.

**Acceptance Scenarios**:

1. **Given** confirmed lineup data exists, **When** the snapshot is built, **Then** the snapshot returns confirmed lineup blocks for both teams.
2. **Given** confirmed lineups are unavailable, **When** the snapshot is built, **Then** the snapshot returns probable lineups plus a source/status marker explaining that the lineup is inferred.

---

### User Story 3 - Keep provider truthfulness explicit (Priority: P2)

As the maintainer, I want the snapshot to attribute each section to its real source and to distinguish unavailable data from zero-valued data so later agents do not reason on fabricated signals.

**Why this priority**: Sprint 1 now spans multiple imperfect sources with different coverage and freshness guarantees.

**Independent Test**: Verify tests and CLI output distinguish `null`/unavailable values, source attribution, and fallback status.

**Acceptance Scenarios**:

1. **Given** an upstream provider lacks a field, **When** the snapshot is built, **Then** the field is represented as unavailable, not as `0` or empty fake data.
2. **Given** the current `transfermarkt-datasets` upstream lacks injury tables, **When** the snapshot is built, **Then** the implementation uses a documented alternative source for injuries and records the actual source in the output.

### Edge Cases

- What happens when a fixture exists but provider team ids were never stored locally?
- What happens when Transfermarkt club mapping resolves market value but not player-level mappings?
- What happens when API-Football returns no confirmed lineups for a future fixture?
- What happens when injury data exists but player names do not align cleanly with lineup candidates?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The fixture cache MUST preserve provider team ids needed for downstream enrichment.
- **FR-002**: The snapshot MUST include per-team market-value context derived from Transfermarkt data.
- **FR-003**: The snapshot MUST include per-team injury availability entries.
- **FR-004**: The snapshot MUST include lineup information for both teams and clearly mark it as `confirmed` or `probable`.
- **FR-005**: The system MUST use a dedicated adapter for Transfermarkt-backed value lookups.
- **FR-006**: The system MUST use a dedicated adapter for lineup/injury provider calls rather than placing provider logic in the CLI.
- **FR-007**: The snapshot MUST expose source attribution for market value, injuries, and lineup sections.
- **FR-008**: The repository MUST include tests for provider-id persistence, Transfermarkt value mapping, injury normalization, lineup normalization, probable-lineup fallback, and CLI output.
- **FR-009**: The docs and continuity artifacts MUST be updated to reflect the fuller Sprint 1 pre-match snapshot scope and the actual upstream source boundaries.

### Key Entities *(include if feature involves data)*

- **TeamMarketValue**: per-team aggregate or leading-player market-value context.
- **InjuryStatus**: player availability record with role/reason/expected return when known.
- **LineupPlayer**: normalized player in a confirmed or probable lineup.
- **TeamLineup**: structured team lineup block with status, formation, and source attribution.
- **PreMatchSnapshot**: the expanded fixture snapshot combining soccerdata, value, injuries, and lineups.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `fixture-snapshot` JSON includes market value, injuries, and lineup sections for both teams.
- **SC-002**: The CLI distinguishes confirmed vs probable lineups in both text and JSON modes.
- **SC-003**: Snapshot output keeps unavailable provider fields as `null` or omitted, never fabricated `0` placeholders.
- **SC-004**: Local lint, tests, verify script, and at least one manual end-to-end snapshot acceptance run pass after implementation.

## Assumptions

- As of 2026-04-24, the official `transfermarkt-datasets` README exposes market-value and lineup-history-friendly tables, but not explicit injury tables.
- Injuries may therefore be sourced from API-Football in this slice while Transfermarkt remains the value and probable-lineup-history source.
- The first probable-lineup implementation can be heuristic as long as it is clearly marked as inferred rather than confirmed.
