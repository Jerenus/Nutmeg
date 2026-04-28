# Feature Specification: Nutmeg Platform Foundation

**Feature Branch**: `001-platform-foundation`  
**Created**: 2026-04-24  
**Status**: Verified  
**Input**: User description: "Build the initial architecture, technical stack, and project skeleton from `Nutmeg-DESIGN-v0.3.md`, using Spec Kit and Superpowers Bridge."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operate the Phase 1 CLI shell (Priority: P1)

As the owner operator, I want a working CLI foundation so I can inspect environment readiness and preview fixtures before the real data connectors are fully implemented.

**Why this priority**: The project is explicitly CLI-first in Phase 1, so the CLI is the first proof that the application boundaries are correct.

**Independent Test**: Run `nutmeg doctor` and `nutmeg fixtures --league epl --demo` in a clean environment and confirm both commands return structured output without requiring external APIs.

**Acceptance Scenarios**:

1. **Given** the project dependencies are installed, **When** the operator runs `nutmeg doctor`, **Then** the CLI reports storage paths, workflow readiness, and provider configuration presence.
2. **Given** no real fixtures have been synced yet, **When** the operator runs `nutmeg fixtures --league epl --demo`, **Then** the CLI returns a coherent demo fixture list for the requested league.

---

### User Story 2 - Preserve multi-tenant-ready domain boundaries (Priority: P2)

As the future maintainer of Phase 2 and Phase 3, I want user identity, quota, repository, and storage seams in place so the Phase 1 code does not trap the project in a single-user dead end.

**Why this priority**: The design doc makes `user_id` propagation a non-negotiable architectural constraint from day one.

**Independent Test**: Inspect the core models and repositories and confirm that mutable state APIs accept `user_id`, and that objective fixture data can be listed without mixing user-scoped preferences.

**Acceptance Scenarios**:

1. **Given** a fixture repository implementation, **When** fixtures are inserted and queried, **Then** the repository API requires `user_id` for mutable state boundaries.
2. **Given** the owner default identity, **When** the application boots, **Then** the identity model exposes tier, preferences, and quota placeholders aligned with Phase 2/3 expansion.

---

### User Story 3 - Enforce specification and reliability workflow (Priority: P3)

As the builder of Nutmeg, I want repository-native spec and reliability artifacts so future feature work is driven by specs, TDD, and verification instead of ad hoc implementation.

**Why this priority**: Nutmeg will evolve across multiple analytical subsystems; disciplined delivery matters as much as the code skeleton.

**Independent Test**: Confirm the repo contains a constitution, a foundation spec/plan/tasks set, Superpowers Bridge installation, and a doctor-style readiness report.

**Acceptance Scenarios**:

1. **Given** a new contributor opens the repository, **When** they read the README and architecture docs, **Then** they can locate the design doc, constitution, ADRs, and execution gates.
2. **Given** the workspace has the required skills installed, **When** reliability readiness is checked, **Then** the bridge reports TDD and verification hooks as ready.

### Edge Cases

- What happens when the workspace is missing required Superpowers skills?
- What happens when the CLI is run before any state database exists?
- What happens when the owner runs the CLI without API credentials in `.env`?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a Typer-based CLI entrypoint for Phase 1 operator workflows.
- **FR-002**: The system MUST provide a `doctor` command that reports configuration, storage, and workflow readiness without contacting external services.
- **FR-003**: The system MUST provide a fixture-listing command that works with demo data before real ETL is available.
- **FR-004**: The system MUST model `user_id`, user tier, quota placeholders, and repository boundaries in the core package.
- **FR-005**: The system MUST include stub modules for agents, prompts, data providers, models, and observability so future sprint work has stable extension points.
- **FR-006**: The repository MUST include architecture docs, ADRs, and a Spec Kit feature package aligned with `Nutmeg-DESIGN-v0.3.md`.
- **FR-007**: The repository MUST confirm Superpowers Bridge readiness for TDD and verification gates.

### Key Entities *(include if feature involves data)*

- **UserIdentity**: The owner/friend/subscriber-ready identity object carrying `user_id`, tier, preferences, and quota placeholders.
- **Fixture**: A normalized upcoming match record that is shared as objective football data.
- **BridgeReport**: The readiness report for Spec Kit + Superpowers reliability hooks.
- **AppSettings**: Runtime configuration for storage, providers, tracing, and default user context.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `uv run nutmeg doctor` completes successfully in a clean local setup with no external API credentials.
- **SC-002**: `uv run nutmeg fixtures --league epl --demo` returns at least two demo fixtures.
- **SC-003**: The repository contains the foundation spec, plan, tasks, constitution, and at least three architecture/reference docs.
- **SC-004**: Local tests cover CLI readiness, domain identity, odds utility behavior, and bridge readiness inspection.

## Assumptions

- Phase 1 remains a private tool operated by a single owner identity.
- Real API-Football, soccerdata, Transfermarkt, and LangGraph integration arrives in later sprint slices.
- The current bootstrap focuses on a modular monolith rather than a distributed deployment.
- Mermaid is supported by the repository hosting surface used for documentation review.
