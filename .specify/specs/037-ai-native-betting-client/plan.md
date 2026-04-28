# Implementation Plan: AI-Native Betting Client

**Branch**: `037-ai-native-betting-client` | **Date**: 2026-04-26 | **Spec**: `.specify/specs/037-ai-native-betting-client/spec.md`
**Input**: Feature specification from `.specify/specs/037-ai-native-betting-client/spec.md`

## Summary

Build a browser/PWA-style Nutmeg client that turns the existing football analysis engine into a subscription-ready betting-analysis workspace. The first implementation keeps Nutmeg's current Python services as the source of truth, adds a client-facing aggregation layer, user-scoped state for watchlists/alerts/entitlements/audits, a small web surface, and CLI parity for all new client payloads.

## Technical Context

**Language/Version**: Python 3.12 backend; HTML, CSS, and small vanilla JavaScript for the browser/PWA surface  
**Primary Dependencies**: Existing Nutmeg stack plus FastAPI, Jinja2, and Uvicorn for the lightweight web/PWA surface  
**Storage**: Existing DuckDB shared analytical cache; existing SQLite mutable state store extended with client user state and audit records  
**Testing**: pytest, FastAPI TestClient/httpx-style route tests, existing `bash scripts/verify.sh`  
**Target Platform**: Local/private web server consumed by desktop and mobile-width browsers; owner/private beta first, subscriber-ready later  
**Project Type**: Web application surface inside the existing modular Python monolith  
**Performance Goals**: Seeded local daily feed and match workspace render within 2 seconds; grounded follow-up answer or refusal within 10 seconds; alert review flow within 1 minute  
**Constraints**: No bet placement, sportsbook connection, guaranteed-profit claims, or dark-pattern gambling UX; deterministic Nutmeg outputs override generated prose; all user state keyed by `user_id`; new client aggregations remain callable from CLI  
**Scale/Scope**: Phase 1 owner/private beta with multi-user-ready state boundaries, entitlement gates, and future subscription seams

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec-First Delivery**: PASS. This work is governed by `.specify/specs/037-ai-native-betting-client/spec.md` and this implementation plan.
- **CLI-First, Bot-Ready Interfaces**: PASS with constraint. The web client introduces a browser surface, but every new client aggregation must also have a JSON CLI command so the workflow remains callable outside the web server.
- **Shared Facts, Isolated User State**: PASS. Objective fixtures, odds, player facts, tactics, and value outputs stay in shared DuckDB/services; watchlists, alerts, entitlements, preferences, and audit records stay in SQLite and carry `user_id`.
- **Evidence-Backed Reliability**: PASS. Tasks must be generated with test-first steps and reviewed by `speckit.superb.review`; implementation must use TDD and verification-before-completion.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Use a server-rendered PWA surface rather than introducing a separate frontend build system or cloud platform.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/037-ai-native-betting-client/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── client-api.yaml
└── tasks.md
```

### Source Code (repository root)

```text
nutmeg/
├── domain/
│   └── client.py                    # Client-facing entities and enums
├── services/
│   └── client.py                    # Daily feed, match workspace, Q&A, alerts, audit orchestration
├── storage/
│   └── client_state_repository.py   # SQLite user state, watchlist, alerts, entitlements, audit records
├── interfaces/
│   ├── cli.py                       # Adds client-feed, client-match, client-question, client-status commands
│   └── client_web.py                # FastAPI app factory and web route handlers
└── interfaces/web/
    ├── templates/client/
    │   ├── layout.html
    │   ├── feed.html
    │   ├── match.html
    │   └── status.html
    └── static/client/
        ├── app.css
        ├── app.js
        └── manifest.webmanifest

tests/
├── test_client_domain.py
├── test_client_service.py
├── test_client_state_repository.py
├── test_client_web.py
└── test_cli.py                      # Extended with client command JSON contract tests

docs/architecture/
└── ai-native-client.md
```

**Structure Decision**: Add the client as a thin application surface inside the existing Python package. Do not create a separate frontend project in this slice. The client service becomes the boundary between existing Nutmeg intelligence and both the web UI and CLI JSON commands.

## Phase 0: Research Output

Research decisions are recorded in `.specify/specs/037-ai-native-betting-client/research.md`.

## Phase 1: Design and Contracts Output

- Data model: `.specify/specs/037-ai-native-betting-client/data-model.md`
- HTTP/UI contract: `.specify/specs/037-ai-native-betting-client/contracts/client-api.yaml`
- Operator quickstart: `.specify/specs/037-ai-native-betting-client/quickstart.md`
- Agent context: `AGENTS.md` now points to this plan.

## Post-Design Constitution Check

- **Spec-First Delivery**: PASS. All downstream work maps to the 037 spec, data model, contracts, and tasks.
- **CLI-First, Bot-Ready Interfaces**: PASS. Plan includes JSON CLI parity for feed, match workspace, follow-up, and status payloads.
- **Shared Facts, Isolated User State**: PASS. The data model separates `EvidenceItem` and match facts from `ClientUser`, `SubscriptionEntitlement`, `WatchlistItem`, `Alert`, and `AnalysisAuditRecord`.
- **Evidence-Backed Reliability**: PASS. Tasks must include failing tests before implementation and be reviewed before code begins.
- **Phase-1 Simplicity, Phase-3 Readiness**: PASS. Server-rendered PWA plus repository seams preserves future subscription migration without early cloud complexity.

## Complexity Tracking

No constitution violations require justification.
