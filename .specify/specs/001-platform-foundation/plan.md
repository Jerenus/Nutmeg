# Implementation Plan: Nutmeg Platform Foundation

**Branch**: `001-platform-foundation` | **Date**: 2026-04-24 | **Spec**: `.specify/specs/001-platform-foundation/spec.md`
**Input**: Feature specification from `.specify/specs/001-platform-foundation/spec.md`

## Summary

Build the Phase 1 Nutmeg bootstrap as a Python 3.12 modular monolith with a working CLI, multi-tenant-ready core models, repository seams, and repository-native delivery governance. The implementation favors runnable local behavior over premature live integrations.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: Typer, Rich, Pydantic Settings, SQLAlchemy  
**Storage**: SQLite for mutable state, DuckDB reserved as the analytical cache target  
**Testing**: pytest  
**Target Platform**: local macOS/Linux development, personal VPS next  
**Project Type**: CLI-first modular monolith  
**Performance Goals**: instant local CLI startup; demo fixture responses in under one second  
**Constraints**: no external API calls required for bootstrap verification; `user_id` must remain visible at state boundaries  
**Scale/Scope**: single owner now, multi-user-ready architecture later

## Constitution Check

- **Spec-first delivery**: PASS — the work is anchored to v0.3 and this feature package.
- **CLI-first**: PASS — the first runnable artifacts are CLI commands.
- **Shared facts, isolated user state**: PASS — user-aware repositories and identities are part of the core bootstrap.
- **Evidence-backed reliability**: PASS — Superpowers Bridge is installed and inspected.
- **Phase-1 simplicity**: PASS — live providers remain as stubs, not hard dependencies.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/001-platform-foundation/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── tasks.md
```

### Source Code (repository root)

```text
config/
├── leagues.yaml
├── teams.yaml
└── users/owner/preferences.yaml

docs/
├── architecture/overview.md
├── adr/ADR-001-spec-driven-foundation.md
├── adr/ADR-002-cli-first-interfaces.md
├── adr/ADR-003-phase1-storage-boundary.md
└── superpowers/reliability-gates.md

nutmeg/
├── agents/
├── config/
├── core/
├── data/
├── domain/
├── interfaces/
├── models/
├── observability/
├── process/
├── services/
└── storage/

scripts/
└── verify.sh

tests/
├── test_cli.py
├── test_identity.py
├── test_betting.py
├── test_router.py
└── test_superpowers_bridge.py
```

**Structure Decision**: Use one Python application package with explicit domain/service/repository seams. This keeps Phase 1 simple while preserving future extraction points.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Multiple top-level docs | Architecture and workflow governance are first-class scope | Hiding them inside README would weaken future delivery discipline |
| Repository abstraction in bootstrap | Multi-tenant migration is a design constraint from day one | Direct SQL calls would make Phase 2 migration harder |
