# Implementation Plan: Odds Event Cache Recovery

**Branch**: `012-odds-event-cache-recovery` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/012-odds-event-cache-recovery/spec.md`

## Summary

Make The Odds API fixture-to-event cache self-healing for stale upstream event ids by adding explicit event invalidation to the repository contract and retrying reconciliation exactly once for stale/not-found odds endpoint responses.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: httpx, DuckDB repositories, existing odds provider clients  
**Storage**: existing `odds_provider_events` table; add repository delete operation only  
**Testing**: pytest + ruff  
**Constraints**: no new provider state leaks into canonical snapshot; retry only stale/not-found class failures; preserve existing provider error behavior for other failures

## Structure Decision

Keep stale detection inside `TheOddsApiClient`, because only the provider adapter understands which upstream status codes/messages indicate a stale event id. Keep invalidation inside `OddsEventRepository` so storage remains behind a protocol boundary.
