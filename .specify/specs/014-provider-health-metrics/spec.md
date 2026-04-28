# Feature Specification: Provider Health Metrics

**Feature Branch**: `014-provider-health-metrics`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue odds reliability roadmap by exposing lightweight provider-health metrics for The Odds API reconciliation and stale-cache recovery.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Observe event-cache behavior (Priority: P1)

As the Nutmeg operator, I want The Odds API client to expose cache hit/miss and reconciliation counters so I can tell whether fixture odds are using cached event links or paying the cost of event lookup.

**Independent Test**: Run cached and uncached odds fetches and verify the health snapshot records cache hits, cache misses, reconcile attempts, and last event id.

### User Story 2 - Observe stale-cache recovery (Priority: P1)

As the Nutmeg operator, I want stale event refreshes and reconciliation failures to be counted so reliability regressions are visible in tests and future CLI/status surfaces.

**Independent Test**: Trigger stale cached event recovery and failed replacement reconciliation, then verify the health snapshot records stale refresh attempts, successes/failures, and last error.

### User Story 3 - Keep metrics non-invasive (Priority: P2)

As a downstream consumer, I want provider-health metrics to avoid changing canonical odds snapshots until there is a dedicated status surface.

**Independent Test**: Verify odds snapshot domain output remains unchanged while client-level health can be inspected separately.
