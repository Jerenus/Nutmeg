# Implementation Plan: Pre-Match Snapshot Completion Sprint 1 Slice

**Branch**: `004-pre-match-snapshot` | **Date**: 2026-04-24 | **Spec**: `.specify/specs/004-pre-match-snapshot/spec.md`
**Input**: Feature specification from `.specify/specs/004-pre-match-snapshot/spec.md`

## Summary

Extend the existing fixture snapshot so one cached fixture can return a fuller pre-match context: soccerdata stats, Transfermarkt market-value context, injury availability, and confirmed-or-probable lineups with source attribution.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: Typer, Rich, DuckDB, HTTPX, soccerdata, pandas  
**Storage**: DuckDB shared cache for fixtures and analytical lookups; SQLite mutable state unchanged  
**Testing**: pytest  
**Target Platform**: local CLI and personal VPS  
**Project Type**: CLI-first modular monolith  
**Performance Goals**: build one expanded snapshot in one CLI call with bounded provider fan-out  
**Constraints**: preserve shared-facts/user-state boundary; expose honest source attribution; probable lineups must be labeled inferred  
**Scale/Scope**: one fixture-at-a-time pre-match snapshot

## Constitution Check

- **Spec-first delivery**: PASS — this larger Sprint 1 step is tracked in a dedicated feature package.
- **CLI-first**: PASS — the work extends the existing `fixture-snapshot` CLI path.
- **Shared facts, isolated user state**: PASS — enrichment remains read-only against shared fixture data.
- **Evidence-backed reliability**: PASS — this slice is delivered via TDD and full verification.
- **Phase-1 simplicity**: PASS — the implementation favors adapters and heuristics over premature workflow orchestration.

## Project Structure

```text
.specify/specs/004-pre-match-snapshot/
├── spec.md
├── plan.md
└── tasks.md

docs/architecture/
└── fixture-snapshot.md

nutmeg/
├── data/api_football.py
├── data/transfermarkt.py
├── domain/fixtures.py
├── domain/snapshot.py
├── interfaces/cli.py
├── services/snapshot.py
├── storage/bootstrap.py
└── storage/fixture_repository.py

tests/
├── test_api_football.py
├── test_cli.py
├── test_fixture_repository.py
└── test_snapshot_service.py
```

**Structure Decision**: keep the existing `fixture-snapshot` slice and deepen it through provider adapters plus domain-model expansion, rather than adding a second overlapping CLI path.
