# Implementation Plan: Zucai Source Parser v0

**Branch**: `043-zucai-source-parser-v0` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/043-zucai-source-parser-v0/spec.md`  
**Input**: Feature specification from `.specify/specs/043-zucai-source-parser-v0/spec.md`

## Summary

Add a local-first `zucai-source-sync` workflow that parses official-like traditional足彩 schedule notices, writes valid 14-match issue snapshots, updates the 042 scheduled issue registry, preserves operator-maintained odds/override paths, and exposes safe JSON/text CLI output. Live URL fetch is opt-in only and bounded; tests use bundled local samples.

## Technical Context

**Language/Version**: Python 3.12 baseline  
**Primary Dependencies**: Existing Typer CLI/dataclass stack, stdlib regex/html parsing, optional `httpx` already present for bounded live fetch  
**Storage**: Local source files, generated `*-issue.json` snapshots, and `.nutmeg-data/zucai/issues.json` registry  
**Testing**: pytest parser/service/CLI tests, `bash scripts/verify.sh`  
**Target Platform**: Local/private operator CLI and scheduled-delivery pre-step  
**Project Type**: Modular Python CLI/service monolith  
**Performance Goals**: Parse bundled schedule sample and write registry in under 1 second  
**Constraints**: No default network, no odds automation in this slice, no bet placement, no guaranteed-profit language  
**Scale/Scope**: Small schedule notices with one or more traditional足彩14场 issue sections

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec-First Delivery**: PASS. Feature is governed by `.specify/specs/043-zucai-source-parser-v0/spec.md` and a Superpowers design doc.
- **CLI-First, Bot-Ready Interfaces**: PASS. `zucai-source-sync` is the primary surface and feeds `zucai-auto-run`.
- **Shared Facts, Isolated User State**: PASS. Parsed schedules are shared local facts; no user-state table is introduced.
- **Evidence-Backed Reliability**: PASS. Tasks require TDD and fresh focused/full verification.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local parser preserves future seams for richer official/API providers.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/043-zucai-source-parser-v0/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── source-sync-result.schema.json
│   └── cli-contract.md
├── tasks.md
└── verification.md
```

### Source Code (repository root)

```text
nutmeg/
├── domain/
│   └── zucai_source.py           # Parsed issue and source sync result models
├── services/
│   └── zucai_source.py           # Source text extraction, issue parsing, registry sync, optional live fetch
├── interfaces/
│   └── cli.py                    # zucai-source-sync command and optional auto-run pre-sync hooks if needed
└── zucai/
    └── samples/
        └── 26068-source-notice.html

tests/
├── test_zucai_source_service.py
└── test_cli.py                   # Extended with zucai-source-sync CLI contracts

docs/architecture/
└── zucai-source-parser.md
```

**Structure Decision**: Keep source parsing separate from `zucai_schedule` and `zucai` report generation. `zucai_source` produces snapshots/registry; `zucai_schedule` decides whether to run; `zucai` generates reports.

## Phase 0: Research Output

Research decisions are recorded in `.specify/specs/043-zucai-source-parser-v0/research.md`.

## Phase 1: Design and Contracts Output

- Data model: `.specify/specs/043-zucai-source-parser-v0/data-model.md`
- CLI/result contracts: `.specify/specs/043-zucai-source-parser-v0/contracts/`
- Quickstart: `.specify/specs/043-zucai-source-parser-v0/quickstart.md`
- Agent context: `AGENTS.md` points to this plan.

## Post-Design Constitution Check

- **Spec-First Delivery**: PASS. Spec, plan, research, model, contracts, quickstart, tasks, and verification are colocated.
- **CLI-First, Bot-Ready Interfaces**: PASS. The parser writes the registry consumed by `zucai-auto-run`.
- **Shared Facts, Isolated User State**: PASS. Registry updates remain local and inspectable.
- **Evidence-Backed Reliability**: PASS. RED/GREEN and verification tasks are explicit.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Future source providers can feed the same sync result contract.

## Complexity Tracking

No constitution violations require justification.
