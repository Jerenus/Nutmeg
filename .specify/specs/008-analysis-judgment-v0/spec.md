# Feature Specification: Analysis Judgment v0

**Feature Branch**: `008-analysis-judgment-v0`  
**Created**: 2026-04-25  
**Status**: Verified
**Input**: User description: "Start the first agent-facing analysis slice so Nutmeg can turn fixture snapshot + odds snapshot context into a direct pre-match judgment in the house style."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce a direct pre-match judgment from cached context (Priority: P1)

As the Nutmeg operator, I want to request a match analysis for a fixture that already exists locally so I can get one explicit call instead of manually reading multiple snapshots.

**Why this priority**: Snapshot and odds infrastructure already exist, but the agent surface is still missing. This slice turns those data paths into the first usable analysis workflow.

**Independent Test**: Run a CLI analysis command against a cached fixture with snapshot and odds context available and verify it returns the required four-part judgment structure.

**Acceptance Scenarios**:

1. **Given** a fixture exists in the local cache and the supporting snapshot services return usable context, **When** the operator requests a pre-match analysis, **Then** Nutmeg returns one structured response with `judgment`, `core_reasons`, `counterargument`, and `confidence`.
2. **Given** some supporting sections are unavailable, **When** the analysis is built, **Then** Nutmeg remains truthful about missing evidence and still produces a constrained answer only if enough evidence remains.

---

### User Story 2 - Combine snapshot and odds evidence without bluffing (Priority: P1)

As the Nutmeg operator, I want the analysis layer to explicitly combine team context and market context so each recommendation is evidence-backed rather than pure prompt text.

**Why this priority**: Nutmeg's value is in synthesis. A judgment that ignores the existing snapshot and odds stack would not justify the prior architecture work.

**Independent Test**: Build the analysis service with deterministic snapshot and odds fixtures and verify the returned reasons cite evidence from both sources when available.

**Acceptance Scenarios**:

1. **Given** snapshot evidence and odds evidence are both available, **When** Nutmeg builds the analysis, **Then** at least one core reason references team/squad context and at least one references market context.
2. **Given** odds data is unavailable but snapshot data is available, **When** the analysis is built, **Then** Nutmeg does not fabricate market evidence and marks that limitation in the reasoning.

---

### User Story 3 - Expose the first analysis workflow through the CLI (Priority: P2)

As the Nutmeg operator, I want a dedicated CLI command for analysis judgment so I can use Nutmeg as an opinionated football assistant rather than as disconnected utility commands.

**Why this priority**: The CLI is the current product surface. The first agent slice should be directly runnable there before any bot or LangGraph orchestration work.

**Independent Test**: Run the CLI in text and JSON modes and verify the response contract is stable, readable, and truthful on failure paths.

**Acceptance Scenarios**:

1. **Given** the operator requests JSON output, **When** the analysis succeeds, **Then** Nutmeg returns a machine-readable payload containing the fixture, intent, evidence summary, and four-part judgment.
2. **Given** the fixture is unknown or the evidence is too thin to support a judgment, **When** the operator runs the command, **Then** Nutmeg fails cleanly with an explicit explanation instead of pretending confidence.

### Edge Cases

- What happens when the fixture exists but odds are unavailable or not configured?
- What happens when snapshot sections contain explicit `null` / unavailable markers for important fields?
- What happens when the query is informational rather than decisional?
- What happens when the evidence is contradictory across squad form and market pricing?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST expose a dedicated CLI workflow that builds a first pre-match analysis judgment for a cached fixture.
- **FR-002**: The analysis workflow MUST consume the existing fixture snapshot and odds snapshot services rather than reimplementing provider logic.
- **FR-003**: The analysis output MUST always use the house four-part structure: `judgment`, `core_reasons`, `counterargument`, `confidence`.
- **FR-004**: The analysis workflow MUST remain truthful about missing or unavailable evidence and MUST NOT fabricate tactical, squad, or market facts.
- **FR-005**: The analysis workflow MUST include an evidence summary that distinguishes snapshot-derived context from odds-derived context.
- **FR-006**: The analysis workflow MUST support both text and JSON CLI output.
- **FR-007**: The query intent classification layer MUST remain part of the flow and be surfaced in the analysis payload.
- **FR-008**: If evidence is too thin for a direct call, Nutmeg MUST fail clearly or return an explicit insufficient-evidence judgment rather than fake confidence.
- **FR-009**: Tests MUST cover the analysis service, CLI text/JSON rendering, intent handling, unavailable-odds behavior, and insufficient-evidence behavior.
- **FR-010**: Architecture and continuity artifacts MUST be updated so this slice becomes the new first agent-facing path in the repo.

### Key Entities *(include if feature involves data)*

- **AnalysisJudgment**: the structured four-part decision output plus confidence and caveats.
- **AnalysisEvidenceSummary**: the normalized summary of snapshot and odds signals consumed by the judgment path.
- **FixtureAnalysisResult**: the full CLI-facing payload containing fixture metadata, intent, evidence summary, and judgment.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The operator can run one command against a cached fixture and receive a complete four-part judgment without manually stitching snapshot and odds output.
- **SC-002**: JSON output preserves fixture metadata, intent classification, evidence summary, and judgment structure in a stable contract.
- **SC-003**: The analysis remains explicit about unavailable odds or sparse evidence instead of bluffing.
- **SC-004**: Local tests and verification pass after implementation.

## Assumptions

- This slice is heuristic and deterministic; it does not yet require LangGraph orchestration or live LLM calls.
- The first delivery focuses on pre-match judgment from existing fixture and odds context, not tactical charts or generated images.
- Snapshot data remains the primary team-context source and odds data remains the primary market-context source.
