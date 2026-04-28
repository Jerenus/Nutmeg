# Research: Event Data Tactical Models v0

## Decision: Local StatsBomb-like JSON provider seam

**Decision**: Use local JSON files in either StatsBomb-like shape or a simplified Nutmeg event shape. The provider normalizes records into `FootballEvent` objects without network access.

**Rationale**: StatsBomb Open Data publishes JSON files with events under match-id files and documents that events/lineups are provided as JSON files exported from the StatsBomb Data API. A local parser lets Nutmeg validate against that ecosystem while keeping tests deterministic and no-network. Source: StatsBomb Open Data README (`events` and `lineups` JSON structure) at https://github.com/statsbomb/open-data/blob/master/README.md.

**Alternatives considered**:

- Download StatsBomb Open Data during CLI runs: rejected because verification should stay no-network and reproducible.
- Add a provider-specific package: rejected until the stable Nutmeg event abstraction exists.
- Keep only existing proxy tactical visuals: rejected because it does not close the event-data gap.

## Decision: xT-lite heuristic before trained xT

**Decision**: Implement a deterministic xT-lite grid value function over normalized 120x80 coordinates and compute positive/negative deltas for successful progressive passes/carries.

**Rationale**: This creates an explainable spatial-value report from event data without requiring large training sets or external dependencies.

**Alternatives considered**:

- Train xT from historical event data: rejected for v0 because training data volume and model validation are separate specs.
- Use hardcoded aggregate xG proxy only: rejected because it ignores event-sequence spatial progression.

## Decision: VAEP-lite contribution labels

**Decision**: Implement VAEP-lite as a labeled heuristic combining shot xG, xT-lite action deltas, and simple defensive-action credit.

**Rationale**: Full VAEP requires trained possession-value models and outcome labels. A clearly labeled v0 heuristic gives usable player contribution ranking without overclaiming.

**Alternatives considered**:

- Full VAEP model: rejected for v0 due training/data requirements.
- No player contributions: rejected because user story requires event-data model outputs to inform tactical/player analysis.

## Decision: Deterministic inline SVG artifacts

**Decision**: Generate pure SVG strings for pass network, xT heatmap, and contribution bars, with optional file writes.

**Rationale**: Existing tactical visuals already use local SVG. Keeping this pattern avoids heavy plotting dependencies while preserving future replacement with mplsoccer.

**Alternatives considered**:

- Add mplsoccer now: rejected for dependency complexity before event abstraction stabilizes.
- Output data only: rejected because visual artifacts are needed for future client/Telegram surfaces.
