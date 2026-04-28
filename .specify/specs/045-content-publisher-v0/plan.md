# Implementation Plan: Content Publisher v0

**Branch**: `045-content-publisher-v0` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/045-content-publisher-v0/spec.md`  
**Input**: Feature specification from `.specify/specs/045-content-publisher-v0/spec.md`

## Summary

Add an independent content-production module that turns existing Zucai report JSON into human-reviewable sports-analysis content packs. The service ranks content-worthy matches, calls OpenClaw's LLM interface for structured Chinese drafts, enforces disclaimers, gates every surface through local compliance rules, and writes JSON/Markdown artifacts for manual review instead of auto-publishing.

## Technical Context

**Language/Version**: Python 3.12 baseline  
**Primary Dependencies**: Existing Typer CLI, dataclass domain models, stdlib subprocess/json/pathlib, existing Zucai report JSON contract, OpenClaw CLI for live LLM generation  
**Storage**: Local JSON and Markdown artifacts under `.nutmeg-data/content` by default; no new database tables  
**Testing**: pytest service/CLI tests with fake LLM providers; `bash scripts/verify.sh` for full regression  
**Target Platform**: macOS/local operator CLI, OpenClaw-ready JSON output  
**Project Type**: Modular Python CLI/service monolith  
**Performance Goals**: Candidate scoring is local and sub-second; LLM generation is bounded by per-match OpenClaw timeout; deterministic tests never make live LLM calls  
**Constraints**: No external platform auto-publishing, no gambling instructions, no profit claims, no paid-pick/private-group calls, no surprise network in tests  
**Scale/Scope**: One Zucai issue report per run, default 1-3 content packs, Chinese-first artifacts

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec-First Delivery**: PASS. This feature is governed by `.specify/specs/045-content-publisher-v0/spec.md` and a Superpowers design doc.
- **CLI-First, Bot-Ready Interfaces**: PASS. `content-pack` is the primary interface and returns JSON for OpenClaw/router consumption.
- **Shared Facts, Isolated User State**: PASS. v0 introduces no user mutable state; artifacts are operator-local review outputs.
- **Evidence-Backed Reliability**: PASS. Tasks require TDD, focused tests, lint, compile, full verification, and graph refresh.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local artifacts and provider seams preserve future platform publisher adapters without adding platform automation now.
- **LLM Boundary**: PASS WITH CONTEXT. The constitution prefers provider boundaries; the user explicitly asked for the current OpenClaw LLM interface. The module uses an `LlmProvider` seam and a single OpenClaw CLI adapter rather than embedding provider secrets or direct ad hoc model calls.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/045-content-publisher-v0/
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
│   └── content.py              # Content candidate, compliance, pack, batch, artifact dataclasses
├── services/
│   └── content.py              # Candidate scoring, LLM prompting/parsing, compliance checks, artifact writing
├── content/
│   ├── __init__.py
│   └── samples/
│       └── 26068-content-report.json
└── interfaces/
    └── cli.py                  # content-pack command and OpenClaw provider builder

tests/
├── test_content_service.py
└── test_cli.py                 # Extended with content-pack CLI contracts

docs/architecture/
└── content-publisher.md
```

**Structure Decision**: Add a separate `content` domain/service instead of extending `zucai`. Zucai owns issue/recommendation generation; content publisher owns topic selection, LLM content generation, compliance gating, and review artifacts.

## Phase 0: Research Output

Research decisions are recorded in `.specify/specs/045-content-publisher-v0/research.md`.

## Phase 1: Design and Contracts Output

- Data model: `.specify/specs/045-content-publisher-v0/data-model.md`
- CLI contract: `.specify/specs/045-content-publisher-v0/contracts/cli-contract.md`
- Quickstart: `.specify/specs/045-content-publisher-v0/quickstart.md`
- Agent context: `AGENTS.md` points to this plan.

## Post-Design Constitution Check

- **Spec-First Delivery**: PASS. Spec, plan, research, model, contract, quickstart, tasks, and verification live together.
- **CLI-First, Bot-Ready Interfaces**: PASS. CLI JSON is the stable contract; future OpenClaw router action can wrap it without duplicating logic.
- **Shared Facts, Isolated User State**: PASS. No user state introduced.
- **Evidence-Backed Reliability**: PASS. RED/GREEN and full verification are explicit tasks.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Output artifacts can later feed Douyin/WeChat/Zhihu publisher adapters.

## Complexity Tracking

No constitution violations require additional justification.
