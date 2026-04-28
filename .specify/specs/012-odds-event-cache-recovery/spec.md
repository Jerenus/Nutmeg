# Feature Specification: Odds Event Cache Recovery

**Feature Branch**: `012-odds-event-cache-recovery`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue odds roadmap by making The Odds API cached fixture-to-event links self-healing when upstream event ids rotate or disappear.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Recover stale cached provider events (Priority: P1)

As the Nutmeg operator, I want The Odds API odds snapshots to recover when a cached event id no longer resolves upstream, so one stale cache row does not permanently break fixture odds.

**Independent Test**: Seed a cached event mapping, make its odds endpoint return 404, then return a fresh event from `/events` and verify `fetch_fixture_odds` retries with the new event id.

**Acceptance Scenarios**:

1. **Given** a cached The Odds API event id returns a stale/not-found response, **When** Nutmeg fetches fixture odds, **Then** it invalidates that cached mapping, re-runs fixture-to-event reconciliation, stores the replacement event, and fetches odds through the replacement id.
2. **Given** the replacement event can be reconciled, **When** odds are fetched, **Then** the final snapshot remains a normal canonical odds snapshot rather than exposing provider-cache internals.

---

### User Story 2 - Fail truthfully when recovery cannot reconcile (Priority: P1)

As the Nutmeg operator, I want cache recovery failures to explain that the cached event was stale and no replacement was found.

**Independent Test**: Seed a cached event mapping, make its odds endpoint return 404, make `/events` return no candidate, and verify a clear provider error is raised.

**Acceptance Scenarios**:

1. **Given** a cached event is stale and no replacement event matches the local fixture, **When** Nutmeg retries reconciliation, **Then** it raises a truthful `TheOddsApiError` and does not silently return an empty odds snapshot.
2. **Given** a non-stale provider error occurs, **When** Nutmeg fetches odds, **Then** it fails as before and does not repeatedly reconcile on every HTTP error.

---

### User Story 3 - Keep repository contract explicit (Priority: P2)

As a future odds provider implementer, I want cache invalidation to be a first-class repository operation rather than ad-hoc SQL inside the provider adapter.

**Independent Test**: Verify the DuckDB odds event repository can delete a fixture/provider event mapping without disturbing unrelated mappings.

**Acceptance Scenarios**:

1. **Given** an event mapping exists, **When** Nutmeg invalidates the fixture/provider mapping, **Then** subsequent reads for that mapping return `None`.
2. **Given** another provider or fixture mapping exists, **When** one mapping is invalidated, **Then** unrelated mappings remain available.
