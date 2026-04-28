# Feature Specification: Tactics Synthesis v0

**Feature Branch**: `009-tactics-synthesis-v0`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: User description: "Deepen the first analysis workflow so Nutmeg can produce a more football-native pre-match read using tactical matchup evidence, contradiction handling, and a stronger synthesis contract before full agent orchestration."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Surface tactical matchup signals in the analysis output (Priority: P1)

As the Nutmeg operator, I want `analyze-match` to include tactical matchup signals derived from the existing snapshot context so the answer sounds like football analysis rather than only market commentary.

**Why this priority**: Sprint 2 in the design doc starts with tactics analysis. The first analysis slice needs football-native evidence before more orchestration layers are added.

**Independent Test**: Run the analysis flow with deterministic snapshot fixtures containing lineup, availability, and matchup context, then verify the output includes explicit tactical evidence in both text and JSON forms.

**Acceptance Scenarios**:

1. **Given** snapshot context includes lineup, matchup, or availability signals, **When** the operator runs `analyze-match`, **Then** Nutmeg includes at least one tactical or matchup reason in the evidence summary.
2. **Given** tactical inputs are sparse, **When** the analysis runs, **Then** Nutmeg marks tactical evidence as limited instead of pretending specificity.

---

### User Story 2 - Handle contradictory evidence without bluffing confidence (Priority: P1)

As the Nutmeg operator, I want the synthesis layer to recognize when team-context signals and market-context signals disagree so the final judgment can stay assertive but honest.

**Why this priority**: The current deterministic slice can only lean on one side. Contradiction handling is the minimum step from a simple formatter to a credible synthesis layer.

**Independent Test**: Run service-level tests where tactical/snapshot signals point one way while odds signals point another, and verify the judgment lowers confidence and calls out the disagreement explicitly.

**Acceptance Scenarios**:

1. **Given** snapshot evidence favors the home side while odds evidence favors the away side, **When** the synthesis runs, **Then** Nutmeg states the disagreement explicitly in the counterargument or caveats and lowers confidence.
2. **Given** both tactical and market evidence align, **When** the synthesis runs, **Then** Nutmeg can keep a direct call with higher confidence than a contradictory case.

---

### User Story 3 - Stabilize the analysis contract for future agent orchestration (Priority: P2)

As the Nutmeg operator, I want the analysis payload to expose structured evidence buckets for tactics, market, and caveats so later agent orchestration can reuse them without rewriting the interface contract.

**Why this priority**: This slice should prepare the repo for a later Router + SynthesisAgent step without forcing LangGraph into the current milestone.

**Independent Test**: Verify the JSON payload includes distinct tactical, snapshot, odds, and caveat sections and that CLI text rendering remains readable.

**Acceptance Scenarios**:

1. **Given** the operator requests JSON output, **When** the analysis succeeds, **Then** the payload exposes distinct tactical evidence, snapshot evidence, odds evidence, and caveats.
2. **Given** the workflow hits insufficient evidence, **When** the operator runs the command, **Then** the failure remains explicit and contract-safe.

### Edge Cases

- What happens when the lineup context exists for only one side?
- What happens when matchup context is present but odds data is stale or unavailable?
- What happens when both sides carry similarly weak or similarly strong tactical signals?
- What happens when informational queries still should not become a direct betting-style call?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST extend the analysis workflow with a distinct tactical evidence bucket derived from the existing snapshot context.
- **FR-002**: The analysis workflow MUST remain deterministic and MUST NOT require live LLM generation for this slice.
- **FR-003**: The analysis output MUST expose separate tactical, general snapshot, odds, and caveat sections in JSON output.
- **FR-004**: The synthesis logic MUST detect contradictory evidence between team-context and market-context signals and reduce confidence when disagreement is material.
- **FR-005**: Tactical evidence MUST remain truthful about missing lineup or matchup context and MUST NOT fabricate specifics.
- **FR-006**: Text output MUST remain aligned with Nutmeg's four-part house style while still surfacing the richer evidence buckets.
- **FR-007**: Tests MUST cover aligned evidence, contradictory evidence, sparse tactical evidence, and CLI rendering stability.
- **FR-008**: Continuity and architecture docs MUST describe this slice as the bridge from deterministic analysis to future agent orchestration.

### Key Entities *(include if feature involves data)*

- **TacticalEvidenceSummary**: normalized tactical or matchup signals extracted from the fixture snapshot.
- **SynthesisConflictState**: explicit record of whether team-context and market-context evidence align or conflict.
- **FixtureAnalysisResult**: extended to expose richer evidence buckets while keeping the four-part judgment stable.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `analyze-match` can surface at least one tactical evidence item when the snapshot contains enough structure.
- **SC-002**: Contradictory evidence paths lower confidence and are explained explicitly.
- **SC-003**: JSON output remains stable while exposing richer evidence sections for future agent reuse.
- **SC-004**: Local tests and verification pass after implementation.
