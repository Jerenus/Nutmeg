# Implementation Plan: Zucai Odds Source v0

**Branch**: `044-zucai-odds-source-v0` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/044-zucai-odds-source-v0/spec.md`  
**Input**: Feature specification from `.specify/specs/044-zucai-odds-source-v0/spec.md`

## Summary

Add a local-first `zucai-odds-sync` workflow that parses official-like or cached odds tables, writes odds snapshots compatible with the 041 report service, updates the 042 registry with `odds_file` or `revision_odds_file`, preserves issue/override paths from 043/manual work, and safely rejects live URL fetch unless explicitly enabled.

## Technical Context

**Language/Version**: Python 3.12 baseline  
**Primary Dependencies**: Existing Typer CLI/dataclass stack, stdlib regex/html parsing, `httpx` for opt-in bounded fetch  
**Storage**: Generated `*-odds.json` snapshots and `.nutmeg-data/zucai/issues.json` registry  
**Testing**: pytest parser/service/CLI tests, `bash scripts/verify.sh`  
**Target Platform**: Local/private operator CLI and scheduled delivery pre-step  
**Project Type**: Modular Python CLI/service monolith  
**Performance Goals**: Parse bundled odds sample and update registry in under 1 second  
**Constraints**: No default network, no bookmaker account integration, no bet placement, no guaranteed-profit language  
**Scale/Scope**: One issue and one slot per sync invocation, 14 odds rows

## Constitution Check

- **Spec-First Delivery**: PASS. Feature is governed by `.specify/specs/044-zucai-odds-source-v0/spec.md` and a Superpowers design doc.
- **CLI-First, Bot-Ready Interfaces**: PASS. `zucai-odds-sync` is the primary surface and feeds `zucai-auto-run`.
- **Shared Facts, Isolated User State**: PASS. Odds snapshots are shared local facts; no user-state table is introduced.
- **Evidence-Backed Reliability**: PASS. Tasks require TDD and fresh focused/full verification.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local parser preserves future seams for richer odds providers and movement analysis.

## Project Structure

```text
.specify/specs/044-zucai-odds-source-v0/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── odds-sync-result.schema.json
│   └── cli-contract.md
├── tasks.md
└── verification.md
```

```text
nutmeg/
├── domain/
│   └── zucai_odds_source.py      # Odds sync result model
├── services/
│   └── zucai_odds_source.py      # Odds source parsing, snapshot writing, registry update
├── interfaces/
│   └── cli.py                    # zucai-odds-sync command
└── zucai/
    └── samples/
        ├── 26068-odds-source-afternoon.html
        └── 26068-odds-source-revision.html

tests/
├── test_zucai_odds_source_service.py
└── test_cli.py                   # Extended with zucai-odds-sync CLI contracts

docs/architecture/
└── zucai-odds-source.md
```

**Structure Decision**: Keep odds parsing separate from schedule parsing and report generation. `zucai_odds_source` writes odds snapshots; `zucai_schedule` selects slot files; `zucai` consumes odds in reports.

## Phase 0: Research Output

Research decisions are recorded in `.specify/specs/044-zucai-odds-source-v0/research.md`.

## Phase 1: Design and Contracts Output

- Data model: `.specify/specs/044-zucai-odds-source-v0/data-model.md`
- CLI/result contracts: `.specify/specs/044-zucai-odds-source-v0/contracts/`
- Quickstart: `.specify/specs/044-zucai-odds-source-v0/quickstart.md`
- Agent context: `AGENTS.md` points to this plan.

## Post-Design Constitution Check

All gates remain PASS. No complexity violations.
