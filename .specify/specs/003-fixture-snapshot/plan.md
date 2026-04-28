# Implementation Plan: Fixture Snapshot Sprint 1 Slice

**Branch**: `003-fixture-snapshot` | **Date**: 2026-04-24 | **Spec**: `.specify/specs/003-fixture-snapshot/spec.md`
**Input**: Feature specification from `.specify/specs/003-fixture-snapshot/spec.md`

## Summary

Implement the first Sprint 1 enrichment path by loading one cached fixture from DuckDB, mapping it into soccerdata-compatible identifiers, fetching FBref + Understat team data, and returning a structured fixture snapshot through the CLI.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: Typer, Rich, DuckDB, soccerdata, pandas  
**Storage**: DuckDB shared fixture cache + SQLite mutable state (unchanged)  
**Testing**: pytest  
**Target Platform**: local CLI and personal VPS  
**Project Type**: CLI-first modular monolith  
**Performance Goals**: build one snapshot in a single CLI call while keeping external source calls constrained to one FBref read plus one Understat read path  
**Constraints**: unsupported leagues must fail explicitly; no silent regression of the shared-facts/user-state boundary; this slice stops before Transfermarkt and lineups  
**Scale/Scope**: one fixture-at-a-time enrichment path

## Constitution Check

- **Spec-first delivery**: PASS — this slice is tracked in its own feature package.
- **CLI-first**: PASS — the new behavior is surfaced as a CLI command.
- **Shared facts, isolated user state**: PASS — the snapshot reads shared fixture data and does not introduce user-state leakage.
- **Evidence-backed reliability**: PASS — the slice is implemented via TDD and verified locally.
- **Phase-1 simplicity**: PASS — snapshot generation stays read-only and does not introduce extra storage yet.

## Project Structure

```text
.specify/specs/003-fixture-snapshot/
├── spec.md
├── plan.md
└── tasks.md

config/
├── leagues.yaml
└── teams.yaml

docs/architecture/fixture-snapshot.md

nutmeg/
├── config/catalog.py
├── config/team_catalog.py
├── core/repositories.py
├── data/soccerdata_client.py
├── domain/snapshot.py
├── interfaces/cli.py
├── services/snapshot.py
└── storage/fixture_repository.py

tests/
├── test_cli.py
├── test_fixture_repository.py
├── test_snapshot_service.py
└── test_team_catalog.py
```

**Structure Decision**: add one vertical slice centered on snapshot assembly; keep source mapping and snapshot normalization separate from CLI orchestration.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Two source readers in one slice | Sprint 1 explicitly requires FBref + Understat together | Doing only one source would not prove the cross-source stitching path |
| Explicit team mappings | Provider naming differs for clubs like Tottenham | Naive string equality would make snapshot generation brittle |
