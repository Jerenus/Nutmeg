# Feature Specification: Historical Fixtures Ingestion

**Feature Branch**: `015-historical-fixtures-ingestion`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue Sprint 1 context quality by ingesting historical fixture rows and using them to compute rest-days in pre-match snapshots.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sync recent historical fixtures (Priority: P1)

As the Nutmeg operator, I want fixture sync to optionally include recent completed fixtures so the local cache contains enough context for rest-days and recent schedule load.

**Independent Test**: Run fixture sync with `past_days > 0` and verify API-Football is requested with a date range that starts before `now` and ends after `now`.

**Acceptance Scenarios**:

1. **Given** `past_days` is configured, **When** fixture sync runs, **Then** the provider request includes both historical and upcoming date range.
2. **Given** historical fixtures are returned with finished status and scores, **When** they are persisted, **Then** the shared fixture cache round-trips those results.

---

### User Story 2 - Query team rest context (Priority: P1)

As the snapshot workflow, I need to find each team's most recent finished fixture before kickoff so environment context can include rest days.

**Independent Test**: Persist past and future fixtures, then verify repository lookup returns only the most recent finished prior fixture for the selected team.

**Acceptance Scenarios**:

1. **Given** multiple prior fixtures exist for a team, **When** rest context is requested before a target kickoff, **Then** the most recent finished prior fixture is selected.
2. **Given** only future or unfinished fixtures exist, **When** rest context is requested, **Then** no rest-days value is fabricated.

---

### User Story 3 - Fill snapshot rest days truthfully (Priority: P1)

As the Nutmeg operator, I want richer pre-match snapshots to include home and away rest-days when historical fixture cache supports it.

**Independent Test**: Build a snapshot with previous finished fixtures for both teams and verify `environment.home_rest_days` and `environment.away_rest_days` are populated.

**Acceptance Scenarios**:

1. **Given** previous finished fixtures are cached for both teams, **When** `fixture-snapshot` runs, **Then** home/away rest days are integer day gaps from prior match date to target kickoff date.
2. **Given** previous fixtures are absent, **When** `fixture-snapshot` runs, **Then** rest days remain `None`.
