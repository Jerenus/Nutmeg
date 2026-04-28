# Feature Specification: Odds Snapshot and Fair Probability

**Feature Branch**: `007-odds-snapshot`  
**Created**: 2026-04-24  
**Status**: Verified
**Input**: User description: "Enter the odds snapshot / fair probability sprint, choose the provider path, build the provider integration skeleton, and complete implementation plus acceptance."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Capture a pre-match odds snapshot (Priority: P1)

As the Nutmeg operator, I want to fetch a structured pre-match odds snapshot for a synced fixture so I can inspect bookmaker coverage and the main market prices around the match without leaving the CLI.

**Why this priority**: Odds ingestion is the foundation for every later market-analysis workflow. Without a reliable snapshot, fair probability and value analysis cannot start.

**Independent Test**: Run the odds snapshot workflow against a cached fixture with available odds and verify the output returns fixture metadata, bookmaker coverage, update time, and normalized market prices.

**Acceptance Scenarios**:

1. **Given** a fixture already exists in the local fixture cache and pre-match odds are available upstream, **When** the operator requests an odds snapshot, **Then** Nutmeg returns fixture-linked odds data with bookmaker coverage, update timestamp, and supported market sections.
2. **Given** some bookmakers or markets are missing for a fixture, **When** the odds snapshot is built, **Then** Nutmeg preserves the available quotes and marks missing sections explicitly instead of fabricating prices.

---

### User Story 2 - Derive fair probabilities from bookmaker prices (Priority: P1)

As the Nutmeg operator, I want the snapshot to convert bookmaker prices into no-vig fair probabilities and fair odds so I can see market-implied expectations instead of only raw decimal odds.

**Why this priority**: Raw odds are not directly comparable across books or markets. The fair-probability layer is the first actionable analytical step on the odds side.

**Independent Test**: Build an odds snapshot from deterministic bookmaker quotes and verify the supported two-way and three-way markets expose probabilities that sum to one, fair odds, and best-price context.

**Acceptance Scenarios**:

1. **Given** a complete three-outcome market or two-outcome market, **When** Nutmeg derives the fair view, **Then** it removes the bookmaker margin and returns fair probabilities and fair odds for each outcome.
2. **Given** multiple bookmakers quote the same supported market, **When** Nutmeg builds the fair view, **Then** it returns consensus fair probability, average available price, best available price, and bookmaker coverage count for each outcome.

---

### User Story 3 - Inspect odds output from the CLI with future-provider seams preserved (Priority: P2)

As the Nutmeg operator, I want a dedicated CLI workflow and stable output contract for odds snapshots so I can review the market view today while keeping room to add a second odds provider later.

**Why this priority**: The operator needs a usable surface immediately, but the data boundary must stay replaceable so later provider additions do not force a rewrite.

**Independent Test**: Run the CLI in text and JSON modes for an existing fixture and verify the output contract is stable, source-attributed, and still behaves truthfully when no odds are available or the provider is not configured.

**Acceptance Scenarios**:

1. **Given** an odds snapshot exists for a fixture, **When** the operator requests JSON output, **Then** the command returns a machine-readable snapshot with fixture, market, fair-probability, and source metadata.
2. **Given** the fixture is unknown or odds are unavailable, **When** the operator runs the command, **Then** Nutmeg fails cleanly or returns explicit unavailability instead of ambiguous partial output.

### Edge Cases

- What happens when a fixture exists locally but upstream pre-match odds are not yet posted?
- What happens when a bookmaker returns duplicate or malformed selection rows for the same market?
- What happens when a supported market is missing one required outcome, making a no-vig calculation invalid?
- What happens when the odds provider is not configured or returns an empty response for a valid fixture?
- What happens when market naming is inconsistent across providers but the consumer contract must stay stable?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST build an odds snapshot against a fixture that already exists in the shared local fixture cache.
- **FR-002**: Nutmeg MUST expose fixture-linked pre-match odds metadata including source name, provider update time, and bookmaker coverage count.
- **FR-003**: Nutmeg MUST normalize supported main markets into a stable output contract, including match winner, both teams to score, and at least one standard totals line when the full market is available.
- **FR-004**: Nutmeg MUST preserve available bookmaker quotes for supported markets and keep unavailable or incomplete markets explicitly unavailable.
- **FR-005**: Nutmeg MUST derive no-vig fair probabilities and fair odds for supported two-way and three-way markets only when the complete outcome set exists.
- **FR-006**: Nutmeg MUST expose consensus fair probability, average available price, best available price, and bookmaker coverage count for each supported outcome.
- **FR-007**: Nutmeg MUST render the odds snapshot and fair-probability view through a dedicated CLI workflow in both text and JSON forms.
- **FR-008**: Nutmeg MUST fail cleanly when the fixture is unknown or the odds provider is not configured, and MUST remain truthful when odds are simply unavailable.
- **FR-009**: Nutmeg MUST retain source attribution for provider data and clearly separate raw bookmaker prices from derived fair probabilities.
- **FR-010**: Nutmeg MUST keep the odds provider boundary replaceable so a second provider can be added later without changing the consumer-facing service contract.
- **FR-011**: Nutmeg MUST persist and expose fixture-linked historical odds summaries for canonical markets when prior snapshots exist, including movement and fair-vs-current drift signals.
- **FR-012**: Tests MUST cover normalization, duplicate handling, fair-probability derivation, CLI rendering, history rendering, provider-selection behavior, and unavailable-provider behavior.
- **FR-013**: Architecture and continuity artifacts MUST be updated to reflect the new odds snapshot slice, provider choice, and historical-odds behavior.

### Key Entities *(include if feature involves data)*

- **OddsSnapshot**: the fixture-linked market snapshot containing source metadata, bookmaker coverage, and normalized supported markets.
- **MarketSnapshot**: a supported betting market with raw quotes, derived fair view, and explicit availability status.
- **OutcomeSnapshot**: one outcome within a supported market, including best price, average price, consensus fair probability, and fair odds.
- **OddsProviderCatalog**: the stable provider-facing mapping for bookmaker and market identifiers that supports future provider expansion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The operator can request an odds snapshot for a synced fixture and receive a structured response with fixture metadata, supported markets, and source attribution in one command.
- **SC-002**: For every supported complete market, the returned fair probabilities are mathematically coherent and sum to one within rounding tolerance.
- **SC-003**: The CLI clearly distinguishes configured-provider failures, no-odds-yet states, and fully available snapshots.
- **SC-004**: When repeated snapshots exist, the operator can inspect explicit movement/drift summaries without recomputing provider-specific history logic in the CLI.
- **SC-005**: Local verification and at least one live odds acceptance run succeed after implementation.

## Assumptions

- This slice covers pre-match odds only; live/in-play odds remain out of scope.
- The first delivery focuses on a stable set of supported main markets rather than every bookmaker-specific bet type.
- Fair probability in this slice means bookmaker-margin removal from market prices, not a proprietary predictive model.
- The shared local fixture cache remains the identity anchor for odds workflows.
- API-Football remains the default primary provider, while The Odds API is now a reconciliation-backed secondary provider for leagues with configured sport-key mappings.
