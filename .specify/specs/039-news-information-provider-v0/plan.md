# Implementation Plan: News Information Provider v0

**Branch**: `039-news-information-provider-v0` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/039-news-information-provider-v0/spec.md`
**Input**: Feature specification from `.specify/specs/039-news-information-provider-v0/spec.md`

## Summary

Add a local-first news/information provider seam that reads deterministic JSON and RSS/Atom-style files, normalizes source-attributed match updates, deduplicates and filters them by fixture/team, exposes a `fixture-information` CLI command, and plugs the digest into the AI-native match workspace information panel.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: Existing Nutmeg stack; standard-library JSON, XML, email date parsing, and pathlib for v0  
**Storage**: Local information source files and bundled deterministic sample data; no new database tables in v0  
**Testing**: pytest, Typer CLI tests, existing `bash scripts/verify.sh`  
**Target Platform**: Local CLI/operator environment, AI-native Web/PWA client, future Telegram reuse  
**Project Type**: Modular Python monolith with domain/service/CLI/client layers  
**Performance Goals**: Seeded fixture digest under 1 second; client workspace remains renderable when information source fails  
**Constraints**: No scraping or network fetch in v0; rumor/unverified labels must be visible; information alone must not raise actionability  
**Scale/Scope**: Single-fixture local information digests over small JSON/RSS files; future live source fetching remains out of scope

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec-First Delivery**: PASS. This feature is governed by `.specify/specs/039-news-information-provider-v0/spec.md` and this plan.
- **CLI-First, Bot-Ready Interfaces**: PASS. The digest is exposed through `nutmeg fixture-information --format json`.
- **Shared Facts, Isolated User State**: PASS. Information items are objective/shared fixture context; no user-specific state is introduced.
- **Evidence-Backed Reliability**: PASS. Tasks include RED tests before implementation and verification-before-completion evidence.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local files and RSS/Atom parsing preserve future live source seams without premature scraping/API coupling.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/039-news-information-provider-v0/
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
│   └── information.py          # Information item/source/digest dataclasses
├── services/
│   └── information.py          # Local JSON/RSS parser, filtering, digest builder
├── information/
│   ├── __init__.py
│   └── samples/
│       └── epl-001-information.json
├── services/
│   └── client.py               # Uses information provider payload when configured
└── interfaces/
    └── cli.py                  # fixture-information command and client service wiring

tests/
├── test_information_service.py
├── test_client_service.py
└── test_cli.py

docs/architecture/
└── information-provider.md
```

**Structure Decision**: Add a dedicated information domain/service rather than embedding parsing in the AI client. `ClientService` consumes a provider seam through `build_information()` so future live providers can replace the local one.

## Phase 0: Research Output

Research decisions are recorded in `.specify/specs/039-news-information-provider-v0/research.md`.

## Phase 1: Design and Contracts Output

- Data model: `.specify/specs/039-news-information-provider-v0/data-model.md`
- CLI contract: `.specify/specs/039-news-information-provider-v0/contracts/cli-contract.md`
- Quickstart: `.specify/specs/039-news-information-provider-v0/quickstart.md`
- Agent context: `AGENTS.md` points to this plan.

## Post-Design Constitution Check

- **Spec-First Delivery**: PASS. All implementation tasks map to spec, plan, data model, and CLI contract.
- **CLI-First, Bot-Ready Interfaces**: PASS. JSON CLI contract is primary.
- **Shared Facts, Isolated User State**: PASS. No user-specific state introduced.
- **Evidence-Backed Reliability**: PASS. TDD and verify tasks included.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local-first seam keeps future HTTP/RSS/API providers possible.

## Complexity Tracking

No constitution violations require justification.
