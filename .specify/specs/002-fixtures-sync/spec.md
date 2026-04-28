# Feature Specification: Fixtures Sync Sprint 0 Slice

**Feature Branch**: `002-fixtures-sync`  
**Created**: 2026-04-24  
**Status**: Verified  
**Input**: User description: "Align to `Nutmeg-DESIGN-v0.3.md`, implement the real fixtures sync path, then finish the agreed Sprint 0 work including tests, validation, review, and continuity artifacts."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sync real fixtures into shared cache (Priority: P1)

As the Nutmeg operator, I want to sync upcoming fixtures from API-Football into local shared storage so the CLI can show real data instead of demos.

**Why this priority**: This is the core missing Sprint 0 production path.

**Independent Test**: Run `nutmeg fixtures-sync --league epl --days 14` with a valid API key, then run `nutmeg fixtures --league epl --next 14`.

**Acceptance Scenarios**:

1. **Given** a configured API key, **When** the operator runs `nutmeg fixtures-sync`, **Then** Nutmeg fetches fixtures from API-Football and persists them locally.
2. **Given** a completed sync, **When** the operator runs `nutmeg fixtures`, **Then** the CLI lists the synced fixtures from local storage.

---

### User Story 2 - Keep storage aligned with v0.3 boundaries (Priority: P2)

As the future maintainer, I want shared objective data and user-scoped mutable state stored separately so Phase 2 does not require a foundational rewrite.

**Why this priority**: `Nutmeg-DESIGN-v0.3.md` explicitly distinguishes shared facts from isolated user data.

**Independent Test**: Inspect the repository implementations and run storage tests covering DuckDB fixtures and SQLite sync metadata.

**Acceptance Scenarios**:

1. **Given** a fixture sync operation, **When** data is persisted, **Then** objective fixture rows are written to the shared analytical store.
2. **Given** a fixture sync operation, **When** run metadata is persisted, **Then** sync state is written to the mutable state store.

---

### User Story 3 - Make long-running execution resumable (Priority: P3)

As a future coding session, I want clear harness artifacts so I can resume the repository safely with minimal guesswork.

**Why this priority**: The user explicitly requested a long-running agent execution model for this round.

**Independent Test**: Confirm `init.sh`, `agent-progress.md`, `feature-list.json`, and harness docs exist and are referenced from the CLI or docs.

**Acceptance Scenarios**:

1. **Given** a fresh session, **When** it reads the repo continuity artifacts, **Then** it can identify what is done and what remains.
2. **Given** the repo health check, **When** `nutmeg doctor` is executed, **Then** harness readiness is visible alongside workflow readiness.

### Edge Cases

- What happens when the API key is missing?
- What happens when API-Football returns pagination or an empty result set?
- What happens when the API returns a `200` with a populated `errors` field?
- What happens when a sync partially succeeds and then fails mid-run?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a `fixtures-sync` CLI command that syncs upcoming fixtures from API-Football.
- **FR-002**: The system MUST map configured Nutmeg league codes to API-Football league IDs.
- **FR-003**: The system MUST store synced fixture rows in shared local storage.
- **FR-004**: The system MUST store sync-run metadata in mutable local state.
- **FR-005**: The system MUST list synced fixtures through the existing CLI without requiring a live API call.
- **FR-006**: The system MUST expose long-running harness artifacts and report their readiness.
- **FR-007**: The system MUST optionally emit LangSmith traces for CLI operations when tracing is enabled and configured.
- **FR-008**: The repository MUST include tests covering API parsing, storage behavior, sync flow, and CLI behavior.

### Key Entities *(include if feature involves data)*

- **LeagueConfig**: configuration record mapping Nutmeg league code to API-Football league ID and seasonality.
- **Fixture**: normalized shared objective match record.
- **SyncRun**: mutable record describing a sync attempt, outcome, and summary.
- **HarnessReport**: readiness report for long-running continuity artifacts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `nutmeg fixtures-sync` completes locally with mocked tests and with real credentials when available.
- **SC-002**: `nutmeg fixtures --league epl --next 7` reads from local storage after sync, not directly from the API.
- **SC-003**: `nutmeg doctor --format json` reports both workflow readiness and harness readiness.
- **SC-004**: The repository passes lint and tests in CI and locally.

## Assumptions

- Sprint 0 focuses on fixture sync only, not yet on lineups, events, or odds sub-endpoints.
- API-Football league IDs for the first tracked competitions are stable and can live in config.
- Objective fixture data is shared across users; user identity is still relevant for future preferences and decision history.
