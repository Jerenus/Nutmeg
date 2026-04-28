# Implementation Plan: Odds Snapshot and Fair Probability

**Branch**: `007-odds-snapshot` | **Date**: 2026-04-24 | **Spec**: `.specify/specs/007-odds-snapshot/spec.md`
**Input**: Feature specification from `.specify/specs/007-odds-snapshot/spec.md`

## Summary

Add a dedicated odds snapshot path that fetches pre-match odds for a cached fixture, normalizes a stable set of main markets, and computes no-vig fair probabilities plus best-price context. Keep API-Football as the first provider because it already matches Nutmeg's fixture identity flow and is configured in the workspace, while introducing a service boundary that can absorb a second provider later.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: Typer, Rich, HTTPX, DuckDB, pydantic-style dataclasses already in repo  
**Storage**: DuckDB shared cache for fixtures; odds snapshot built on demand in this slice, with optional provider reference caching in shared analytical storage  
**Testing**: pytest  
**Target Platform**: local CLI and personal VPS
**Project Type**: CLI-first modular monolith  
**Performance Goals**: one odds snapshot should complete in a single bounded provider call plus local aggregation, with reference metadata reused or cheaply fetched  
**Constraints**: truthful source attribution; no fabricated probabilities for incomplete markets; preserve replaceable provider seams; keep Sprint scope to pre-match odds  
**Scale/Scope**: one fixture at a time, canonical main markets first, live acceptance on a real EPL fixture

## Constitution Check

- **Spec-first delivery**: PASS — odds work is isolated in a dedicated Spec Kit feature package.
- **CLI-first**: PASS — the primary user surface is a new CLI command backed by a service layer.
- **Shared facts, isolated user state**: PASS — odds data is objective shared data and does not add mutable user state.
- **Evidence-backed reliability**: PASS — implementation will follow test-first tasks and end with fresh live and local verification.
- **Phase-1 simplicity**: PASS — on-demand snapshot + stable provider seam is the smallest useful slice before historical persistence or sharp-book specialization.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/007-odds-snapshot/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── cli-odds-snapshot.md
└── tasks.md
```

### Source Code (repository root)

```text
docs/architecture/
└── odds-snapshot.md

nutmeg/
├── data/
│   └── api_football.py
├── domain/
│   ├── fixtures.py
│   └── odds.py
├── interfaces/
│   └── cli.py
├── models/
│   └── betting.py
├── services/
│   └── odds.py
└── storage/
    └── fixture_repository.py

tests/
├── test_api_football.py
├── test_betting.py
├── test_cli.py
└── test_odds_service.py
```

**Structure Decision**: add a dedicated `nutmeg/domain/odds.py` and `nutmeg/services/odds.py` rather than overloading the pre-match snapshot service. Provider-specific parsing stays inside `nutmeg/data/api_football.py`, while CLI rendering and shared betting math remain reusable across later provider additions.

## Complexity Tracking

No constitution violations are expected for this slice.
