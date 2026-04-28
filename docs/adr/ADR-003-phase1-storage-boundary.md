# ADR-003: Split Phase 1 storage into SQLite state and DuckDB-ready analytics

- **Status**: Accepted
- **Date**: 2026-04-24

## Context

Nutmeg needs lightweight local state now and analytics-friendly storage soon. The design doc already separates mutable state from analytical workloads.

## Decision

Use SQLite for mutable application state in the bootstrap and preserve DuckDB as the analytical cache target behind configuration and repository seams.

## Consequences

- The first runnable slice can use standard SQLAlchemy tooling without analytics-specific runtime requirements.
- The repo can introduce DuckDB-backed ETL and query layers later without rewriting interface code.
- Repository abstractions remain mandatory so PostgreSQL migration stays tractable in Phase 2.
