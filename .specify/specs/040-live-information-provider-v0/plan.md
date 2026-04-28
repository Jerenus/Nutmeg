# Implementation Plan: Live Information Provider v0

**Branch**: `040-live-information-provider-v0` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/040-live-information-provider-v0/spec.md`
**Input**: Feature specification from `.specify/specs/040-live-information-provider-v0/spec.md`

## Summary

Extend the 039 local information digest with an operator-approved source manifest, cache-backed remote RSS/JSON fetches, explicit live-fetch controls, and client/CLI integration. The implementation preserves the existing `InformationItem` and `FixtureInformationDigest` contract while adding source definitions, cache metadata, safe HTTP fetch seams, and stale fallback warnings.

## Technical Context

**Language/Version**: Python 3.12 baseline; current venv may run newer compatible Python locally  
**Primary Dependencies**: Existing Nutmeg stack, `httpx`, standard-library JSON/XML/hashlib/pathlib/datetime  
**Storage**: Local cache files under `.nutmeg-data/information-cache` by default; no new database tables in v0  
**Testing**: pytest, Typer CLI tests, fake injected HTTP fetcher, `bash scripts/verify.sh`  
**Target Platform**: Local CLI/operator environment, AI-native Web/PWA client reuse, future Telegram/OpenClaw routing  
**Project Type**: Modular Python monolith with domain/service/CLI/client layers  
**Performance Goals**: Manifest digest over small feeds under 2 seconds with fake/local sources; HTTP timeout configurable and bounded  
**Constraints**: No scraping; no default network calls; no auth/secrets in v0; max response-size guard; stale cache must be labeled  
**Scale/Scope**: Small trusted source manifests with local files and unauthenticated RSS/JSON URLs for one fixture digest at a time

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec-First Delivery**: PASS. This feature is governed by `.specify/specs/040-live-information-provider-v0/spec.md` and the design note in `docs/superpowers/specs/2026-04-26-live-information-provider-design.md`.
- **CLI-First, Bot-Ready Interfaces**: PASS. `fixture-information` remains the primary surface; `client-match` receives explicit manifest options for reuse.
- **Shared Facts, Isolated User State**: PASS. Source manifests and cache entries are operator-controlled shared source context; no per-user state is introduced.
- **Evidence-Backed Reliability**: PASS. Tasks require TDD, RED evidence, and final verification.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Local cache files and injected fetchers avoid cloud complexity while preserving future API/provider seams.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/040-live-information-provider-v0/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli-contract.md
│   └── source-manifest.schema.json
├── tasks.md
└── verification.md
```

### Source Code (repository root)

```text
nutmeg/
├── domain/
│   └── information.py          # Source definition/cache metadata additions
├── services/
│   └── information.py          # Manifest loader, live/cache provider, HTTP fetch seam
└── interfaces/
    └── cli.py                  # fixture-information/client-match manifest/cache flags

tests/
├── test_information_service.py # Manifest, cache, fetch, stale fallback tests
├── test_client_service.py      # Client workspace manifest-backed provider behavior
└── test_cli.py                 # CLI contract tests for manifest/live/cache flags

docs/architecture/
└── information-provider.md     # Live provider/cache/no-scraping documentation
```

**Structure Decision**: Extend the information domain/service rather than adding a vendor-specific data adapter. The live provider remains a provider seam consumed by `FixtureInformationService`, so future authenticated APIs can implement the same contract.

## Phase 0: Research Output

Research decisions are recorded in `.specify/specs/040-live-information-provider-v0/research.md`.

## Phase 1: Design and Contracts Output

- Data model: `.specify/specs/040-live-information-provider-v0/data-model.md`
- CLI and manifest contracts: `.specify/specs/040-live-information-provider-v0/contracts/`
- Quickstart: `.specify/specs/040-live-information-provider-v0/quickstart.md`
- Agent context: `AGENTS.md` points to this plan.

## Post-Design Constitution Check

- **Spec-First Delivery**: PASS. Spec, plan, research, data model, contracts, quickstart, and tasks are colocated.
- **CLI-First, Bot-Ready Interfaces**: PASS. The CLI JSON contract is primary and reusable by routers.
- **Shared Facts, Isolated User State**: PASS. No user-specific mutable state added.
- **Evidence-Backed Reliability**: PASS. TDD tasks and verification tasks are explicit.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. File cache and injected fetcher are simple but keep future provider replacement straightforward.

## Complexity Tracking

No constitution violations require justification.
