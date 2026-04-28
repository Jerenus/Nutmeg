# Implementation Plan: Historical Fixtures Ingestion

**Branch**: `015-historical-fixtures-ingestion` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/015-historical-fixtures-ingestion/spec.md`

## Summary

Extend fixture sync and fixture repository to support recent historical fixtures, then compute rest-days inside `FixtureSnapshotService` using cached finished fixtures.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: existing API-Football client, DuckDB fixture repository, snapshot service  
**Storage**: existing `fixtures` table already stores status and goals; no schema change required  
**Testing**: pytest + ruff  
**Constraints**: no fabricated rest values; CLI remains backward compatible with `--past-days` defaulting to `0`
