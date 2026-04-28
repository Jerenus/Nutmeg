# Feature Specification: Market Shape Expansion

**Feature Branch**: `010-market-shape-expansion`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: User description: "Deepen the analysis workflow so Nutmeg can reason across multiple pre-match market shapes instead of relying mainly on match winner pricing."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Surface more than one market angle in a single analysis (Priority: P1)

As the Nutmeg operator, I want `analyze-match` to read multiple canonical odds markets so the recommendation can discuss result, goal environment, and risk framing together.

**Why this priority**: Nutmeg's odds layer already normalizes multiple markets. The analysis layer should use that work instead of flattening everything into a single match-winner lean.

**Independent Test**: Run the analysis service against deterministic odds snapshots containing match winner, BTTS, and totals context, then verify the output includes explicit market-shape evidence beyond one winner price.

**Acceptance Scenarios**:

1. **Given** match winner, BTTS, and totals markets are available, **When** Nutmeg builds a pre-match analysis, **Then** the evidence summary includes distinct statements for result and goal-environment context.
2. **Given** only some markets are available, **When** the analysis runs, **Then** Nutmeg uses the available shapes and explicitly marks the missing ones.

---

### User Story 2 - Use market shape to improve judgment framing (Priority: P1)

As the Nutmeg operator, I want the final judgment to incorporate whether the market expects an open or cagey game so the recommendation feels more football-native and betting-aware.

**Why this priority**: A result lean without game-state context is too thin. Over/under and BTTS prices help frame the likely match texture.

**Independent Test**: Run service tests with open-game and low-event pricing and verify the judgment reasons reflect that contrast.

**Acceptance Scenarios**:

1. **Given** totals and BTTS markets imply an open game, **When** the analysis runs, **Then** the reasoning mentions a higher-event environment.
2. **Given** totals and BTTS markets imply a lower-event game, **When** the analysis runs, **Then** the reasoning mentions restraint and reduced scoring expectation.

---

### User Story 3 - Prepare the contract for richer future market slices (Priority: P2)

As the Nutmeg operator, I want the evidence payload to preserve market-shape details in structured form so later slices can add deeper handicap and derivative markets without breaking the analysis contract.

**Why this priority**: This is the right time to stabilize the analysis schema before more orchestration or more market coverage is added.

**Independent Test**: Verify JSON output exposes structured market-shape evidence and text output remains readable.

**Acceptance Scenarios**:

1. **Given** JSON output is requested, **When** the analysis succeeds, **Then** the payload includes a dedicated market-shape evidence section that distinguishes result, totals, and BTTS views.
2. **Given** market coverage is partial, **When** the analysis succeeds, **Then** caveats remain explicit without breaking the response contract.

### Edge Cases

- What happens when totals is available but BTTS is missing?
- What happens when BTTS and totals imply different game textures?
- What happens when match winner is unavailable but goal-environment markets are present?
- What happens when market-shape evidence conflicts with tactical evidence?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST extend analysis evidence with structured market-shape signals beyond `match_winner`.
- **FR-002**: The analysis workflow MUST consume existing normalized odds markets and MUST NOT duplicate provider parsing.
- **FR-003**: The analysis payload MUST distinguish result market evidence from goal-environment evidence.
- **FR-004**: The synthesis logic MUST use totals and BTTS context to describe likely game texture when available.
- **FR-005**: Missing market shapes MUST remain explicit in caveats rather than silently ignored.
- **FR-006**: The four-part house judgment MUST remain stable while incorporating richer market-shape reasons.
- **FR-007**: Tests MUST cover open-game, low-event, and partial-market-coverage paths.
- **FR-008**: Architecture and continuity artifacts MUST document the expanded market-shape contract.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `analyze-match` can mention result and goal-environment evidence in one response when normalized odds markets exist.
- **SC-002**: Open-game vs low-event pricing changes the reasoning in deterministic tests.
- **SC-003**: Partial market coverage remains truthful and contract-safe.
- **SC-004**: Local tests and verification pass after implementation.
