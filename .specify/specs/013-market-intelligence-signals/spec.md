# Feature Specification: Market Intelligence Signals

**Feature Branch**: `013-market-intelligence-signals`  
**Created**: 2026-04-25  
**Status**: Verified  
**Input**: Continue odds roadmap by turning odds history and bookmaker spread into analysis evidence for movement, disagreement, and confidence calibration.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Explain market movement (Priority: P1)

As the Nutmeg operator, I want `analyze-match` to mention meaningful result-market movement so judgments can distinguish static consensus from a live market move.

**Independent Test**: Build an analysis result with match-winner history whose home probability has moved materially and verify market evidence mentions movement and drift.

**Acceptance Scenarios**:

1. **Given** odds history shows a moving match-winner market, **When** Nutmeg analyzes a match, **Then** odds evidence includes a concise movement/drift reason.
2. **Given** odds history is flat or absent, **When** Nutmeg analyzes a match, **Then** it avoids overstating market movement.

---

### User Story 2 - Flag bookmaker disagreement (Priority: P1)

As the Nutmeg operator, I want Nutmeg to detect wide bookmaker dispersion so confidence can be capped when the market consensus is noisy.

**Independent Test**: Build a market with multiple bookmaker quotes and a wide best-vs-average or quote-range spread, then verify caveats and confidence reflect disagreement.

**Acceptance Scenarios**:

1. **Given** bookmaker prices are widely dispersed for a key market, **When** analysis runs, **Then** evidence includes a bookmaker disagreement caveat.
2. **Given** disagreement is high, **When** confidence is computed, **Then** confidence cannot remain `high`.

---

### User Story 3 - Preserve CLI contract (Priority: P2)

As a downstream consumer, I want market intelligence to remain inside existing analysis evidence fields so JSON/text output stays compatible.

**Independent Test**: Run CLI JSON/text tests with movement/disagreement summaries and verify no new top-level payload contract is required.

**Acceptance Scenarios**:

1. **Given** movement and disagreement signals exist, **When** JSON output is requested, **Then** they appear under existing evidence arrays.
2. **Given** text output is requested, **When** analysis renders, **Then** movement appears under market evidence and disagreement under caveats.
