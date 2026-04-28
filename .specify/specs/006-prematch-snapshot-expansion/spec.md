# Feature Specification: Richer Pre-Match Snapshot Expansion

**Feature Branch**: `006-prematch-snapshot-expansion`  
**Created**: 2026-04-24  
**Status**: Verified
**Input**: User description: "Expand the pre-match snapshot with A) environment/schedule context, B) matchup/trend context, and C) deeper squad availability."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Add environment and schedule context (Priority: P1)

As the Nutmeg operator, I want each pre-match snapshot to include venue, referee, weather, kickoff local time, rest days, and away travel context so the environment around the match is visible in one structured view.

**Independent Test**: Build a snapshot with fixture metadata plus cached venue/weather data and verify the environment block is populated with schedule context and source attribution.

**Acceptance Scenarios**:

1. **Given** a fixture has venue and kickoff metadata, **When** the snapshot is built, **Then** it returns venue, kickoff local time, rest days, and away travel context.
2. **Given** a weather forecast exists for the venue and kickoff window, **When** the snapshot is built, **Then** it returns a structured weather block with source attribution.

---

### User Story 2 - Add deeper squad availability context (Priority: P1)

As the Nutmeg operator, I want the snapshot to distinguish injuries, suspensions, returning players, bench depth, and expected absences summary so squad availability is more actionable than a flat injury list.

**Independent Test**: Mock injury/suspension/provider-squad inputs and verify the availability block includes expected absences, potential returns, and bench-depth context.

**Acceptance Scenarios**:

1. **Given** availability records include injuries and suspensions, **When** the snapshot is built, **Then** the output groups them into structured absence categories and a summary.
2. **Given** a team has a materially strong or weak bench by market-value coverage, **When** the snapshot is built, **Then** the snapshot exposes that bench-depth context explicitly.

---

### User Story 3 - Add matchup and trend context (Priority: P2)

As the Nutmeg operator, I want head-to-head, home/away splits, recent goal/xG trends, and set-piece trends so the snapshot captures match-shape signals before kickoff.

**Independent Test**: Build a snapshot with mocked historical provider inputs and verify the matchup/trend block is present and attributable.

**Acceptance Scenarios**:

1. **Given** historical matchup and split data exists, **When** the snapshot is built, **Then** the output includes structured head-to-head and home/away split summaries.
2. **Given** recent trend data exists, **When** the snapshot is built, **Then** the output includes goals/xG and set-piece trends with sample-size transparency.

### Edge Cases

- What happens when referee data is absent for a fixture?
- What happens when a venue cannot be geocoded confidently?
- What happens when a league does not expose enough history for head-to-head or set-piece splits?
- What happens when returning-player confidence is ambiguous?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The snapshot MUST expose an environment/schedule block with venue, kickoff local time, rest days, and away travel context.
- **FR-002**: The snapshot MUST expose a weather block when forecast data is available and keep it explicitly unavailable otherwise.
- **FR-003**: The snapshot MUST expose referee context when available from the fixture provider.
- **FR-004**: The snapshot MUST expand squad availability into injuries, suspensions, returning players, expected absences summary, and bench-depth context.
- **FR-005**: The snapshot MUST expose matchup/trend context including head-to-head, home/away splits, recent goal/xG trend, and set-piece trend.
- **FR-006**: Every new snapshot section MUST carry truthful source attribution and preserve unavailable values explicitly.
- **FR-007**: The CLI text and JSON output MUST render the new richer snapshot sections.
- **FR-008**: Tests MUST cover environment/schedule, availability expansion, matchup/trend calculations, and unavailable-data behavior.
- **FR-009**: Docs and continuity artifacts MUST be updated to reflect the richer pre-match snapshot scope.

### Key Entities *(include if feature involves data)*

- **EnvironmentContext**: venue, referee, kickoff local time, weather, rest days, travel.
- **AvailabilityContext**: injuries, suspensions, returning players, expected absences summary, bench depth.
- **MatchupTrendContext**: head-to-head, splits, goals/xG trend, set-piece trend.
- **RicherPreMatchSnapshot**: the full Sprint 1 snapshot combining prior and new sections.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `fixture-snapshot` JSON includes environment/schedule, availability, and matchup/trend sections for both teams or explicit unavailable markers.
- **SC-002**: The CLI distinguishes unavailable, inferred, and confirmed context without fabricating missing values.
- **SC-003**: Local lint, tests, verify script, and at least one manual richer snapshot acceptance run pass after implementation.
