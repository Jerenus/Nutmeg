# Feature Specification: Asian Handicap Expansion

**Feature Branch**: `011-asian-handicap-expansion`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: User description: "Deepen the odds and analysis stack so Nutmeg can reason over a broader Asian handicap family instead of the first narrow line band only."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Normalize a wider Asian handicap family (Priority: P1)

As the Nutmeg operator, I want Nutmeg to normalize more Asian handicap lines so the odds layer can reflect more realistic pre-match market coverage.

**Why this priority**: The odds architecture explicitly left deeper handicap normalization for a later slice. This is the highest-value next expansion on the odds side.

**Independent Test**: Build odds snapshots against deterministic provider payloads containing broader handicap lines and verify canonical handicap markets are surfaced consistently.

**Acceptance Scenarios**:

1. **Given** provider odds include handicap lines beyond `0.5 / 1.0 / 1.5`, **When** Nutmeg builds an odds snapshot, **Then** the supported handicap lines are normalized into canonical market keys.
2. **Given** provider selection formats differ across sources, **When** Nutmeg parses the handicap markets, **Then** equivalent lines are mapped into the same canonical contract.

---

### User Story 2 - Reuse richer handicap signals in analysis (Priority: P1)

As the Nutmeg operator, I want the analysis workflow to mention handicap pressure when a side is being priced as more than a bare result favorite.

**Why this priority**: Expanding handicap normalization is most useful when the analysis layer can actually consume the extra shape.

**Independent Test**: Run deterministic analysis tests with stronger or weaker handicap support and verify the judgment reasons reflect that difference.

**Acceptance Scenarios**:

1. **Given** the home side is supported on stronger handicap lines, **When** `analyze-match` runs, **Then** the market evidence can mention that the favorite is being priced to win by margin, not just edge the match.
2. **Given** only shallow handicap support exists, **When** `analyze-match` runs, **Then** the market evidence remains cautious and does not overstate margin confidence.

---

### User Story 3 - Keep the odds contract stable while coverage grows (Priority: P2)

As the Nutmeg operator, I want the odds and analysis contracts to stay stable while handicap coverage expands so future slices can build on them safely.

**Why this priority**: This project already has multiple consumers of canonical odds markets. Coverage growth should not make the contract brittle.

**Independent Test**: Verify CLI JSON/text output remains readable and existing market behavior stays intact while richer handicap coverage is added.

**Acceptance Scenarios**:

1. **Given** richer handicap markets are available, **When** the operator requests JSON output, **Then** the contract remains machine-readable and canonical.
2. **Given** no richer handicap markets are available, **When** the operator runs the command, **Then** previous market behavior remains unchanged and truthful.
