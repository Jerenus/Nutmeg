# Implementation Plan: Event Data Tactical Models v0

**Branch**: `038-event-data-tactical-models-v0` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/038-event-data-tactical-models-v0/spec.md`
**Input**: Feature specification from `.specify/specs/038-event-data-tactical-models-v0/spec.md`

## Summary

Add a local-first event-data tactical modeling layer that reads StatsBomb-like or simplified JSON event files, normalizes fixture events, computes pass-network, xT-lite, and VAEP-lite summaries, emits deterministic SVG artifacts, and exposes the report through a CLI command. This closes the remaining event-data modeling gap while avoiding live provider calls and avoiding false claims of full trained model parity.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: Existing Nutmeg stack; standard-library JSON/math/path handling only for v0  
**Storage**: Local JSON event files and bundled deterministic sample data; no new database tables in v0  
**Testing**: pytest, Typer CLI tests, existing `bash scripts/verify.sh`  
**Target Platform**: Local CLI/operator environment with future Web/Telegram reuse  
**Project Type**: Modular Python monolith with domain/service/CLI layers  
**Performance Goals**: Seeded local event report under 1 second; SVG artifact writes deterministic  
**Constraints**: No network download in v0; no heavy plotting dependencies; explicit xT-lite/VAEP-lite labels; do not modify existing tactical proxy flows  
**Scale/Scope**: Single-fixture local event reports over small-to-medium open data files; future provider downloads remain out of scope

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec-First Delivery**: PASS. This feature is governed by `.specify/specs/038-event-data-tactical-models-v0/spec.md` and this plan.
- **CLI-First, Bot-Ready Interfaces**: PASS. The report is exposed first through `nutmeg event-tactical-models --format json`.
- **Shared Facts, Isolated User State**: PASS. Event data is objective fixture data; no user-specific mutable state is introduced.
- **Evidence-Backed Reliability**: PASS. Tasks include RED tests before implementation and verification-before-completion evidence.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local files and deterministic SVG avoid premature provider/download complexity while preserving provider seams.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/038-event-data-tactical-models-v0/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── cli-contract.md
├── tasks.md
└── verification.md
```

### Source Code (repository root)

```text
nutmeg/
├── domain/
│   └── event_data.py          # Normalized events, quality, pass network, model/report dataclasses
├── services/
│   └── event_data.py          # Local event loader, xT-lite, VAEP-lite, SVG artifact builder
├── event_data/
│   ├── __init__.py
│   └── samples/
│       └── epl-001-events.json
└── interfaces/
    └── cli.py                 # event-tactical-models command and builder

tests/
├── test_event_data.py
└── test_cli.py                # Extended with event-tactical-models JSON contract

docs/architecture/
└── event-data-tactical-models.md
```

**Structure Decision**: Add a new event-data domain/service slice rather than expanding proxy tactical visuals. Existing `nutmeg.services.tactics` remains a snapshot proxy visual service; `nutmeg.services.event_data` handles true event-sequence reports.

## Phase 0: Research Output

Research decisions are recorded in `.specify/specs/038-event-data-tactical-models-v0/research.md`.

## Phase 1: Design and Contracts Output

- Data model: `.specify/specs/038-event-data-tactical-models-v0/data-model.md`
- CLI contract: `.specify/specs/038-event-data-tactical-models-v0/contracts/cli-contract.md`
- Quickstart: `.specify/specs/038-event-data-tactical-models-v0/quickstart.md`
- Agent context: `AGENTS.md` points to this plan.

## Post-Design Constitution Check

- **Spec-First Delivery**: PASS. All implementation tasks map to spec, plan, data model, and CLI contract.
- **CLI-First, Bot-Ready Interfaces**: PASS. JSON CLI contract is primary.
- **Shared Facts, Isolated User State**: PASS. No user-specific state introduced.
- **Evidence-Backed Reliability**: PASS. TDD and verify tasks included.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local provider seam keeps future StatsBomb/mplsoccer/trained-model work possible.

## Complexity Tracking

No constitution violations require justification.
