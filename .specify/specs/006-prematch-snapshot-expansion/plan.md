# Implementation Plan: Richer Pre-Match Snapshot Expansion

**Branch**: `006-prematch-snapshot-expansion` | **Date**: 2026-04-24 | **Spec**: `.specify/specs/006-prematch-snapshot-expansion/spec.md`
**Input**: Feature specification from `.specify/specs/006-prematch-snapshot-expansion/spec.md`

## Summary

Extend the current pre-match snapshot with environment/schedule context, deeper squad availability, and matchup/trend sections using the identity/materialization infrastructure from feature 005.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: Typer, Rich, DuckDB, HTTPX, soccerdata, pandas  
**Storage**: DuckDB shared cache for fixture analytics, provider references, venue/weather cache, and trend aggregates; SQLite mutable state unchanged  
**Testing**: pytest  
**Target Platform**: local CLI and personal VPS  
**Project Type**: CLI-first modular monolith  
**Performance Goals**: richer snapshot remains a single CLI call built mostly from local shared caches and bounded provider fan-out  
**Constraints**: preserve truthful source attribution; avoid fabricated predictions; depend on 005 identity/materialization groundwork  
**Scale/Scope**: richer one-fixture pre-match snapshot for Sprint 1 acceptance

## Constitution Check

- **Spec-first delivery**: PASS — richer snapshot scope is isolated in a dedicated feature package.
- **CLI-first**: PASS — the work extends the existing `fixture-snapshot` path.
- **Shared facts, isolated user state**: PASS — all added context is objective shared data.
- **Evidence-backed reliability**: PASS — sections will land via TDD and full verification.
- **Phase-1 simplicity**: PASS — no betting workflow yet; still focused on richer context assembly.

## Project Structure

```text
.specify/specs/006-prematch-snapshot-expansion/
├── spec.md
├── plan.md
└── tasks.md

docs/architecture/
└── fixture-snapshot.md

nutmeg/
├── data/
│   ├── api_football.py
│   ├── open_meteo.py
│   ├── soccerdata_client.py
│   └── transfermarkt.py
├── domain/
│   └── snapshot.py
├── interfaces/
│   └── cli.py
├── services/
│   ├── materialization.py
│   └── snapshot.py
└── storage/
    └── reference_repository.py

tests/
├── test_api_football.py
├── test_cli.py
├── test_snapshot_service.py
└── test_weather.py
```

**Structure Decision**: keep richer snapshot assembly centralized in `FixtureSnapshotService` while pushing provider normalization and cached aggregate queries into dedicated adapters/repositories.
