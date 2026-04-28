# Implementation Plan: Player Identity Alignment and Provider Materialization

**Branch**: `005-player-identity-materialization` | **Date**: 2026-04-24 | **Spec**: `.specify/specs/005-player-identity-materialization/spec.md`
**Input**: Feature specification from `.specify/specs/005-player-identity-materialization/spec.md`

## Summary

Add a shared player-identity and provider-materialization layer under DuckDB so richer snapshot reads become both more accurate across providers and faster across repeated runs.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: Typer, Rich, DuckDB, HTTPX, soccerdata, pandas  
**Storage**: DuckDB shared cache for fixtures, identities, reference tables, and materialized provider tables; SQLite mutable state unchanged  
**Testing**: pytest  
**Target Platform**: local CLI and personal VPS  
**Project Type**: CLI-first modular monolith  
**Performance Goals**: repeated snapshot reads prefer local DuckDB materialized data instead of remote provider fetches  
**Constraints**: preserve truthful source attribution; do not fabricate player matches; keep shared/objective data in DuckDB  
**Scale/Scope**: snapshot support infrastructure for one fixture-at-a-time CLI reads

## Constitution Check

- **Spec-first delivery**: PASS — new infrastructure is isolated in a dedicated feature package.
- **CLI-first**: PASS — refresh and verification flows remain CLI-driven.
- **Shared facts, isolated user state**: PASS — identities, materialized provider data, venue references, and weather cache are shared objective data.
- **Evidence-backed reliability**: PASS — delivery will follow TDD plus full verification.
- **Phase-1 simplicity**: PASS — start with team-scoped matching and bounded materialization, not generalized entity resolution.

## Project Structure

```text
.specify/specs/005-player-identity-materialization/
├── spec.md
├── plan.md
└── tasks.md

config/
├── player_aliases.yaml

docs/architecture/
└── reference-data.md

nutmeg/
├── data/
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
├── storage/
│   ├── bootstrap.py
│   └── reference_repository.py

tests/
├── test_cli.py
├── test_materialization.py
├── test_reference_repository.py
├── test_snapshot_service.py
└── test_weather.py
```

**Structure Decision**: keep identity/materialization as shared infrastructure under storage/services and let snapshot assembly consume it, rather than embedding cache and alias logic inside provider adapters or CLI commands.
