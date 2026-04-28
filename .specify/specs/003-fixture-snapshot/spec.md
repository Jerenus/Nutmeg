# Feature Specification: Fixture Snapshot Sprint 1 Slice

**Feature Branch**: `003-fixture-snapshot`  
**Created**: 2026-04-24  
**Status**: Verified
**Input**: User description: "Continue Sprint 1 first block and stitch soccerdata together with fixture snapshot generation."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build a pre-match snapshot from cached fixture data (Priority: P1)

As the Nutmeg operator, I want to select one cached fixture and build a structured snapshot so I can inspect both teams before later agent workflows arrive.

**Why this priority**: Sprint 1 starts by proving Nutmeg can enrich one real fixture with more than raw schedule data.

**Independent Test**: Seed or sync fixtures, then run `nutmeg fixture-snapshot --fixture-id <id> --format json`.

**Acceptance Scenarios**:

1. **Given** the fixture already exists in the shared cache, **When** the operator requests a snapshot by fixture id, **Then** Nutmeg returns the fixture metadata plus enriched team summaries for the home and away sides.
2. **Given** the fixture id is unknown, **When** the operator requests a snapshot, **Then** Nutmeg fails cleanly with an actionable error message.

---

### User Story 2 - Enrich fixture context with soccerdata season and recent-form signals (Priority: P1)

As the Nutmeg operator, I want the snapshot to include FBref season metrics and Understat recent-form/shot signals so the fixture view is deeper than a plain schedule row.

**Why this priority**: This is the exact first Sprint 1 deliverable named in `Nutmeg-DESIGN-v0.3.md`.

**Independent Test**: Use mocked soccerdata readers in tests and verify that the snapshot contains FBref season shooting metrics plus Understat recent-form aggregates and shot-quality aggregates.

**Acceptance Scenarios**:

1. **Given** a supported domestic league and mapped teams, **When** Nutmeg fetches soccerdata inputs, **Then** the snapshot contains per-team FBref season metrics.
2. **Given** recent Understat data exists, **When** Nutmeg builds the snapshot, **Then** the snapshot contains last-N-match recent form and shot-summary metrics for each team.

---

### User Story 3 - Keep Sprint 1 scope explicit and reliable (Priority: P2)

As the maintainer, I want this slice to stop at `soccerdata + fixture snapshot` so we can verify one reliable block before adding Transfermarkt, lineups, and injuries.

**Why this priority**: The user explicitly narrowed this round to the first Sprint 1 block and asked for full testing, verification, and review.

**Independent Test**: Inspect the spec, CLI help, and docs; verify the snapshot explicitly reports deferred sections rather than pretending those sources already exist.

**Acceptance Scenarios**:

1. **Given** the current Sprint 1 scope, **When** a snapshot is returned, **Then** it marks lineups and injuries as deferred for later slices.
2. **Given** a league lacks a supported soccerdata mapping, **When** the operator requests a snapshot, **Then** Nutmeg fails with a precise unsupported-league message instead of silently returning partial garbage.

### Edge Cases

- What happens when `soccerdata` is not installed in the environment?
- What happens when FBref or Understat does not have a mapping for one of the teams?
- What happens when Understat has no recent matches or no shot events yet for the selected team?
- What happens when the fixture belongs to a competition that API-Football tracks but Understat does not?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a `fixture-snapshot` CLI command that accepts a cached `fixture_id`.
- **FR-002**: The system MUST load the base fixture from the shared fixture cache, not from a fresh upstream fixture API call.
- **FR-003**: The system MUST integrate `soccerdata` through a dedicated adapter module rather than using the library directly in the CLI layer.
- **FR-004**: The system MUST map Nutmeg league codes to source-specific soccerdata league identifiers for FBref and Understat.
- **FR-005**: The system MUST map canonical team names to source-specific team names when the upstream naming differs.
- **FR-006**: The snapshot MUST include per-team FBref season shooting metrics.
- **FR-007**: The snapshot MUST include per-team Understat recent-form aggregates for the last N matches.
- **FR-008**: The snapshot MUST include per-team Understat shot-summary aggregates derived from recent match shot events.
- **FR-009**: The snapshot MUST report which downstream sections are still deferred in this slice.
- **FR-010**: The repository MUST include tests covering team/league mapping, soccerdata normalization, snapshot assembly, and CLI behavior.

### Key Entities *(include if feature involves data)*

- **FixtureSnapshot**: the assembled per-match object combining cached fixture metadata with team enrichment data.
- **TeamSeasonMetrics**: normalized season-long shooting/xG metrics from FBref.
- **TeamRecentForm**: last-N-match results and xG aggregates from Understat.
- **TeamShotSummary**: aggregated shot-event counts and xG totals from Understat shot data.
- **TeamSourceMapping**: canonical-to-source mapping for a team across soccerdata providers.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `nutmeg fixture-snapshot --fixture-id epl-001 --format json` succeeds in tests after `seed-demo` or fixture insertion.
- **SC-002**: The snapshot JSON contains both `home` and `away` team blocks with season metrics, recent form, and shot summary fields.
- **SC-003**: The CLI fails cleanly for unknown fixture ids and unsupported/unmapped leagues.
- **SC-004**: Local lint, tests, and repository verification pass after the slice is implemented.

## Assumptions

- This slice intentionally excludes Transfermarkt, injuries, and lineup extraction.
- Understat support is narrower than API-Football support; unsupported competitions are allowed to fail explicitly.
- The first snapshot focuses on stable numeric summaries, not tactical plots or agent reasoning.
