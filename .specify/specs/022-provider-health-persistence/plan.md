# Implementation Plan: Provider Health Persistence

**Branch**: `022-provider-health-persistence` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/022-provider-health-persistence/spec.md`

## Summary

Add a DuckDB-backed `odds_provider_health` table and repository. The Odds API client will optionally record cumulative health deltas after fetch/reconciliation paths, and `agent-status` will read the latest persisted snapshot without network access.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: DuckDB, existing Typer CLI  
**Storage**: existing analytics DuckDB under `.nutmeg-data/analytics/analytics.duckdb`  
**Testing**: pytest unit/CLI tests with isolated settings and mocked HTTP  
**Constraints**: no live provider calls in tests/status, do not leak keys, do not mutate canonical odds snapshot contracts

## Design

- Extend `TheOddsApiHealthSnapshot` with `updated_at` for persisted latest-state reporting.
- Add `OddsProviderHealthRepository` protocol and `DuckDbOddsProviderHealthRepository` implementation.
- Store one cumulative row per provider in `odds_provider_health` using delete+insert upsert for DuckDB compatibility.
- Inject the optional health repository into `TheOddsApiClient`; persist after successful/failing operations whenever metrics change.
- Extend `build_agent_status_payload()` to include latest persisted health for `the-odds-api` only.
