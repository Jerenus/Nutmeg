# Feature Specification: Player Identity Alignment and Provider Materialization

**Feature Branch**: `005-player-identity-materialization`  
**Created**: 2026-04-24  
**Status**: Verified
**Input**: User description: "Cross-provider player-id / alias alignment, plus local materialization/cache for Transfermarkt and soccerdata so richer pre-match snapshots are accurate and faster."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Align injuries with probable lineups across providers (Priority: P1)

As the Nutmeg operator, I want player availability records to resolve against probable-lineup candidates across providers so missing players are excluded reliably even when provider names differ.

**Why this priority**: The current probable-lineup exclusion still relies on raw player-name equality and can drift across providers.

**Independent Test**: Build a snapshot where API-Football injuries use a different provider name than Transfermarkt lineup candidates and verify the unavailable player is excluded through identity resolution rather than raw name equality.

**Acceptance Scenarios**:

1. **Given** a player exists in the same team under two provider name variants, **When** the snapshot is built, **Then** the resolver links them to the same canonical player identity.
2. **Given** a player cannot be resolved with enough confidence, **When** the snapshot is built, **Then** the system marks the availability entry as unmatched instead of fabricating a precise mapping.

---

### User Story 2 - Prefer local materialized provider data for repeated snapshot reads (Priority: P1)

As the Nutmeg operator, I want provider-heavy snapshot inputs to be materialized locally so repeated snapshot generation is meaningfully faster and less dependent on remote fetch latency.

**Why this priority**: The current manual acceptance path still works, but remote provider reads make end-to-end snapshot generation too slow.

**Independent Test**: Materialize the required reference data, then build the same snapshot twice and verify the second read uses local tables/cache paths.

**Acceptance Scenarios**:

1. **Given** local materialized Transfermarkt and soccerdata tables exist, **When** the snapshot is built, **Then** the service reads from the local cache path instead of remote provider downloads for those sections.
2. **Given** local materialized data is missing or stale, **When** a refresh command is invoked, **Then** the required tables are rebuilt and become available for subsequent snapshot calls.

---

### User Story 3 - Persist venue and weather references for richer snapshot expansion (Priority: P2)

As the maintainer, I want venue geocoding and weather lookups cached locally so the next richer snapshot slice can compute environment context without repeated geocoding calls.

**Why this priority**: Environment context is the next approved Sprint 1 expansion and depends on stable venue references.

**Independent Test**: Resolve a venue once, reuse it on the next request, and verify the weather cache can serve fixture-level context without another geocoding lookup.

**Acceptance Scenarios**:

1. **Given** a fixture venue has already been resolved, **When** environment context is requested again, **Then** the system reuses the stored venue reference.
2. **Given** a weather forecast has already been cached for the venue and kickoff window, **When** the same fixture context is rebuilt, **Then** the cached forecast is reused.

### Edge Cases

- What happens when multiple players on the same team share similar names?
- What happens when player position is missing for one provider but present for another?
- What happens when the local materialized cache exists but the required team/player row is absent?
- What happens when venue geocoding returns multiple plausible matches?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST introduce a canonical player-identity layer for cross-provider player matching.
- **FR-002**: The identity layer MUST support provider-specific aliases and normalized-name matching within team context.
- **FR-003**: The identity layer MUST preserve unresolved or low-confidence matches explicitly rather than fabricating certainty.
- **FR-004**: The snapshot service MUST use canonical player identity resolution when excluding unavailable players from probable lineups.
- **FR-005**: The repository MUST materialize the Transfermarkt tables required for market value and probable lineup inference into local DuckDB.
- **FR-006**: The repository MUST materialize the soccerdata tables required for fixture snapshot enrichment into local DuckDB.
- **FR-007**: The project MUST provide a refresh path for rebuilding the local reference/materialized cache.
- **FR-008**: The project MUST persist venue reference and weather cache tables needed by the next snapshot slice.
- **FR-009**: Tests MUST cover identity matching, unresolved matching, materialized cache reads, refresh behavior, and venue/weather cache reuse.
- **FR-010**: Docs and continuity artifacts MUST be updated to explain the new identity and materialization architecture.

### Key Entities *(include if feature involves data)*

- **PlayerIdentity**: canonical team-scoped player identity used to reconcile provider names and ids.
- **PlayerAlias**: provider-specific alias row pointing at a canonical player identity.
- **MaterializedProviderCache**: locally persisted provider tables for snapshot reads.
- **VenueReference**: canonical venue geocode and timezone reference.
- **WeatherCacheEntry**: cached weather forecast for a venue and kickoff window.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Snapshot probable-lineup exclusion no longer depends only on raw player-name equality.
- **SC-002**: Repeated snapshot builds can read Transfermarkt and soccerdata inputs from local materialized tables.
- **SC-003**: A CLI refresh flow exists for rebuilding required reference/materialized data.
- **SC-004**: Local lint, tests, verify script, and manual cache-backed snapshot acceptance pass after implementation.
