# Implementation Plan: Fixtures Sync Sprint 0 Slice

**Branch**: `002-fixtures-sync` | **Date**: 2026-04-24 | **Spec**: `.specify/specs/002-fixtures-sync/spec.md`
**Input**: Feature specification from `.specify/specs/002-fixtures-sync/spec.md`

## Summary

Implement the real fixture sync path for Sprint 0 using API-Football as the upstream source, DuckDB as the shared fixture cache, SQLite as the mutable state store, and repository-local long-running harness artifacts for session continuity.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: Typer, Rich, HTTPX, DuckDB, SQLAlchemy, LangSmith  
**Storage**: DuckDB shared fixture cache + SQLite mutable state  
**Testing**: pytest  
**Target Platform**: local development and personal VPS  
**Project Type**: CLI-first modular monolith  
**Performance Goals**: sync future 30-day fixtures for configured competitions within a small batch of paginated API calls  
**Constraints**: no silent live API dependency for listing cached fixtures; objective data vs user-state separation must stay explicit  
**Scale/Scope**: seven tracked competitions in Sprint 0

## Constitution Check

- **Spec-first delivery**: PASS — this slice is tracked separately as a feature package.
- **CLI-first**: PASS — all sync and inspection paths are CLI-visible.
- **Shared facts, isolated user state**: PASS — storage is explicitly split.
- **Evidence-backed reliability**: PASS — tests, lint, and verify are part of the slice.
- **Phase-1 simplicity**: PASS — sync is still a modular monolith, no service split.

## Project Structure

```text
.specify/specs/002-fixtures-sync/
├── spec.md
├── plan.md
└── tasks.md

docs/process/long-running-agent-harness.md
feature-list.json
agent-progress.md
init.sh

nutmeg/
├── config/catalog.py
├── data/api_football.py
├── domain/fixtures.py
├── domain/sync.py
├── observability/langsmith.py
├── process/harness.py
├── services/fixtures.py
├── services/sync.py
├── storage/bootstrap.py
├── storage/fixture_repository.py
├── storage/state_models.py
└── storage/sync_run_repository.py
```

**Structure Decision**: extend the existing modular monolith with one new vertical slice centered on fixture sync and cache inspection.
