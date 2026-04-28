# Implementation Plan: Traditional Zucai 14-Match Workflow v0

**Branch**: `041-zucai-14match-workflow-v0` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/041-zucai-14match-workflow-v0/spec.md`
**Input**: Feature specification from `.specify/specs/041-zucai-14match-workflow-v0/spec.md`

## Summary

Add a reusable traditional Chinese Sports Lottery 14-match workflow that loads explicit issue/odds/override snapshots, builds risk-tiered `3/1/0` recommendations and plans, renders Markdown/PDF artifacts, optionally dispatches the PDF through the configured Telegram bot, and grades settled outcomes. The implementation is local-first, CLI-first, and deterministic, with bundled issue 26068 sample data for no-network smoke tests.

## Technical Context

**Language/Version**: Python 3.12 baseline; current project uses Typer CLI and dataclass domain models  
**Primary Dependencies**: Existing Nutmeg stack plus `reportlab` for Chinese-capable PDF rendering  
**Storage**: Local JSON input snapshots and generated artifacts under `.nutmeg-data/zucai` by default; no new database tables in v0  
**Testing**: pytest, Typer CLI tests, focused service tests, `bash scripts/verify.sh`  
**Target Platform**: Local/private operator CLI and OpenClaw/Nutmeg Telegram bot reuse  
**Project Type**: Modular Python monolith with domain/service/CLI layers  
**Performance Goals**: Generate a 14-match sample report and PDF in under 2 seconds in local tests  
**Constraints**: No bet placement, no guaranteed-profit claims, no arbitrary scraping, dry-run dispatch by default, no token leakage  
**Scale/Scope**: One traditional足彩 issue at a time, exactly 14 matches, small local source snapshots

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec-First Delivery**: PASS. This feature is governed by `.specify/specs/041-zucai-14match-workflow-v0/spec.md` and `docs/superpowers/specs/2026-04-26-zucai-14match-workflow-design.md`.
- **CLI-First, Bot-Ready Interfaces**: PASS. `zucai-report` and `zucai-grade` are primary surfaces; Telegram/OpenClaw reuse the same report service.
- **Shared Facts, Isolated User State**: PASS. Issue/odds snapshots and reports are shared operator artifacts; no per-user state is introduced in v0.
- **Evidence-Backed Reliability**: PASS. Tasks require TDD, RED/GREEN evidence, and full verification before status is marked complete.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local files avoid premature cloud state while preserving future parser/storage/calibration seams.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/041-zucai-14match-workflow-v0/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── issue.schema.json
│   ├── odds.schema.json
│   ├── overrides.schema.json
│   └── cli-contract.md
├── tasks.md
└── verification.md
```

### Source Code (repository root)

```text
nutmeg/
├── domain/
│   └── zucai.py                  # Issue, odds, recommendations, plans, reports, grading models
├── services/
│   └── zucai.py                  # Loading, validation, recommendation, rendering, dispatch, grading
├── interfaces/
│   └── cli.py                    # zucai-report and zucai-grade commands
└── zucai/
    └── samples/                  # Bundled deterministic 26068 issue/odds/overrides/outcomes samples

tests/
├── test_zucai_service.py
├── test_cli.py                   # Extended with zucai CLI contracts
└── test_telegram_bot.py          # Extended document sender behavior if needed

docs/architecture/
└── zucai-14match-workflow.md
```

**Structure Decision**: Add a dedicated Zucai domain/service because traditional 14-match pools have issue-level plan construction and grading semantics that do not belong in single-fixture `analysis`, `value`, or `client` services.

## Phase 0: Research Output

Research decisions are recorded in `.specify/specs/041-zucai-14match-workflow-v0/research.md`.

## Phase 1: Design and Contracts Output

- Data model: `.specify/specs/041-zucai-14match-workflow-v0/data-model.md`
- CLI/input contracts: `.specify/specs/041-zucai-14match-workflow-v0/contracts/`
- Quickstart: `.specify/specs/041-zucai-14match-workflow-v0/quickstart.md`
- Agent context: `AGENTS.md` points to this plan.

## Post-Design Constitution Check

- **Spec-First Delivery**: PASS. Spec, plan, research, model, contracts, quickstart, and tasks are colocated.
- **CLI-First, Bot-Ready Interfaces**: PASS. CLI JSON output is the bot/router contract.
- **Shared Facts, Isolated User State**: PASS. No new user-state table introduced.
- **Evidence-Backed Reliability**: PASS. TDD tasks and verification tasks are explicit.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. File snapshots and report artifacts can later be moved into durable storage without changing the report contract.

## Complexity Tracking

No constitution violations require justification.
