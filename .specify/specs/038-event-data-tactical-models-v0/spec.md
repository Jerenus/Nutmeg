# Feature Specification: Event Data Tactical Models v0

**Feature Branch**: `038-event-data-tactical-models-v0`  
**Created**: 2026-04-26  
**Status**: Verified (2026-04-26)  
**Input**: Continue Nutmeg development after all previous specs are verified by closing the remaining event-data tactical modeling gap from the design audit.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Load normalized event data for a fixture (Priority: P1)

As the operator, I want Nutmeg to read local event data for a fixture and normalize passes, shots, carries, and defensive actions, so later models can use true event-level inputs rather than only aggregate proxies.

**Why this priority**: Event parsing is the foundation for pass networks, xT, and player contribution models.

**Independent Test**: Provide a deterministic local JSON event file and verify Nutmeg returns normalized event count, provider metadata, teams, players, locations, outcomes, xG where present, and truthful quality warnings.

**Acceptance Scenarios**:

1. **Given** a local StatsBomb-like event file exists, **When** the fixture is loaded, **Then** events are normalized with fixture id, team, player, type, minute, location, end location, outcome, and source event id.
2. **Given** an event file is missing or empty, **When** the fixture is loaded, **Then** Nutmeg reports event data as unavailable and does not synthesize events.
3. **Given** an event contains unsupported fields, **When** it is parsed, **Then** known fields are preserved and unknown details are kept as provider metadata without breaking the report.

---

### User Story 2 - Build event-data tactical models (Priority: P1)

As the operator, I want a fixture-level tactical report with pass network, xT-lite zone values, and VAEP-lite player contributions, so match analysis can reference actual event sequences when available.

**Why this priority**: This closes the research-grade tactical modeling gap while remaining honest about v0 model limitations.

**Independent Test**: Load a seeded event file and verify the report includes completed-pass network nodes/edges, spatial value deltas for progressive actions, player contribution rankings, model labels, warnings, and unavailable sections.

**Acceptance Scenarios**:

1. **Given** completed passes exist, **When** the report is built, **Then** Nutmeg produces pass-network nodes and edges from actual pass start/end locations and counts.
2. **Given** successful progressive passes or carries exist, **When** xT-lite is computed, **Then** Nutmeg reports per-zone values and player deltas with an explicit xT-lite label.
3. **Given** shots, progressive actions, and defensive actions exist, **When** VAEP-lite contributions are computed, **Then** Nutmeg ranks player contributions and labels the output as a heuristic, not a trained VAEP model.

---

### User Story 3 - Expose event tactical reports from CLI and artifacts (Priority: P2)

As the operator, I want a CLI command that returns text/JSON reports and optional SVG artifacts, so event-data models can feed future client, Telegram, and review workflows.

**Why this priority**: Every Nutmeg workflow must be CLI-first and bot/client-ready.

**Independent Test**: Run the CLI with a local events file, request JSON, and verify the contract includes model metadata, quality state, report sections, and artifact paths when an output directory is provided.

**Acceptance Scenarios**:

1. **Given** an events file is supplied, **When** the CLI runs with JSON output, **Then** stdout is parseable and includes fixture id, event count, quality, pass network, xT-lite, VAEP-lite, artifacts, warnings, and responsible model labels.
2. **Given** an output directory is supplied, **When** artifacts are generated, **Then** SVG files are written deterministically and referenced in the JSON payload.
3. **Given** event data is unavailable, **When** the CLI runs, **Then** it exits successfully with unavailable sections and does not fabricate charts.

### Edge Cases

- Local file path does not exist, is empty, or contains malformed JSON.
- StatsBomb-like records omit location, player, team, pass end location, shot xG, or outcome.
- Only one team has events, or completed passes are too sparse for a meaningful network.
- Coordinate ranges differ from the expected 120x80 football pitch scale.
- Event types are unknown or provider-specific.
- xT-lite or VAEP-lite could be over-interpreted as full research models.
- SVG output directory already exists or must be created.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Nutmeg MUST provide normalized event-data entities for fixture events, event quality, pass networks, spatial value, player contribution, and report artifacts.
- **FR-002**: Nutmeg MUST load local JSON event files in a StatsBomb-like or simplified schema without requiring network access.
- **FR-003**: Missing, empty, or malformed event data MUST be reported as unavailable or partial without fabricated events.
- **FR-004**: Event normalization MUST preserve fixture id, event id, provider, team, player, event type, period, minute, second, start location, end location where available, outcome, xG where available, and provider metadata.
- **FR-005**: The tactical report MUST include pass-network nodes and edges derived from completed pass events when available.
- **FR-006**: The tactical report MUST include xT-lite spatial value summaries for successful progressive passes and carries when available.
- **FR-007**: The tactical report MUST include VAEP-lite player contribution summaries while explicitly labeling them as heuristic, not trained VAEP.
- **FR-008**: The tactical report MUST include warnings and unavailable sections whenever event data is insufficient for a model section.
- **FR-009**: Nutmeg MUST generate deterministic SVG artifacts for pass network, xT-lite heatmap, and contribution summaries when inputs exist.
- **FR-010**: The CLI MUST expose `event-tactical-models` with `--fixture-id`, optional `--events-file`, optional `--output-dir`, and `--format text|json`.
- **FR-011**: CLI JSON output MUST remain machine-parseable and include model labels, quality state, event count, report sections, artifacts, and warnings.
- **FR-012**: Event-data models MUST remain local-first and must not alter existing proxy tactical visuals or fixture snapshot behavior.
- **FR-013**: Documentation MUST explain the difference between xT-lite/VAEP-lite v0 heuristics and full research-grade trained models.

### Key Entities *(include if feature involves data)*

- **Football Event**: A normalized event-level record tied to one fixture with provider id, type, team/player identity, time, locations, outcome, and provider metadata.
- **Event Data Quality**: The fixture-level availability state, event count, provider, warnings, and generated timestamp.
- **Pass Network**: Aggregated nodes and edges created from completed pass events.
- **Spatial Value Summary**: xT-lite zone values and progressive action deltas.
- **Player Contribution Summary**: VAEP-lite offensive/defensive/total contribution estimates by player.
- **Event Tactical Report**: The full fixture-level report containing quality, pass network, spatial value, player contributions, SVG artifacts, warnings, and unavailable sections.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A seeded local event file can be normalized into at least 10 fixture events in under 1 second during tests.
- **SC-002**: A seeded fixture report produces pass-network, xT-lite, and VAEP-lite sections with explicit model labels and at least one warning about v0 limitations.
- **SC-003**: Missing or empty event data returns a successful unavailable report with zero fabricated events in 100% of tests.
- **SC-004**: CLI JSON output is parseable and includes artifact metadata when `--output-dir` is used.
- **SC-005**: Existing tactical visuals, match brief, value board, and AI-native client tests continue to pass unchanged.

## Assumptions

- v0 uses local JSON files and bundled deterministic samples instead of downloading provider data.
- StatsBomb Open remains the reference event schema shape, but Nutmeg accepts simplified local records for testing and future providers.
- xT-lite and VAEP-lite are explanatory heuristics for local analysis, not production betting edges or full academic model parity.
- Future specs may add provider downloads, mplsoccer rendering, trained xT/VAEP, or client integration once the event abstraction is stable.
