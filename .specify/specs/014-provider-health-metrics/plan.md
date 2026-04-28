# Implementation Plan: Provider Health Metrics

**Branch**: `014-provider-health-metrics` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/014-provider-health-metrics/spec.md`

## Summary

Add a lightweight in-process health snapshot to `TheOddsApiClient` that records fixture-to-event cache usage, reconciliation attempts/failures, stale refresh attempts/successes, and last event/error metadata.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing odds provider adapter  
**Storage**: none in this slice  
**Testing**: pytest + ruff  
**Constraints**: no canonical odds snapshot schema change; deterministic counters only; no external metrics dependency
