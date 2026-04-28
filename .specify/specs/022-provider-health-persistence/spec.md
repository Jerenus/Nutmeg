# Feature Specification: Provider Health Persistence

**Feature Branch**: `022-provider-health-persistence`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Persist The Odds API provider health metrics across CLI/process invocations so operational diagnosis is not lost after a command exits.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Persist provider health after odds operations (Priority: P1)

As the operator, I want The Odds API cache/reconciliation/stale-refresh counters and last error/event to survive after the process exits.

**Independent Test**: Execute The Odds API client operations with a DuckDB-backed health repository, instantiate a new repository/client, and verify the latest snapshot contains cumulative counters and last event/error.

### User Story 2 - Surface persisted provider health in status (Priority: P1)

As the operator, I want `nutmeg agent-status --format json` to include persisted provider health when The Odds API is configured without making any network call.

**Independent Test**: Seed provider health in DuckDB and verify CLI status reports the counters while not leaking keys.

### User Story 3 - Keep health persistence non-invasive (Priority: P2)

As future maintainers, I need provider health persistence to stay outside canonical odds snapshot data and avoid breaking API-Football/default paths.

**Independent Test**: Existing odds snapshot tests continue passing, API-Football provider construction remains unchanged, and provider health appears only in status/health APIs.
