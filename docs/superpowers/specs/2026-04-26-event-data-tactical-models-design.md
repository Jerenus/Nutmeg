# Event Data Tactical Models v0 Design

Date: 2026-04-26

## Context

Nutmeg already has local tactical visual proxies, fixture snapshots, value-board models, player profiles, and the AI-native client. The remaining v0.3 research-grade gap is true event-data modeling: pass networks from actual events, spatial value models, and player contribution estimates. The next slice should add this capability without disrupting the existing operator loop.

## Selected Approach

Implement a local-first event-data tactical model layer with a StatsBomb-like JSON parser, deterministic sample data, and no network dependency. This gives Nutmeg an event-data seam now while keeping future provider integrations replaceable.

Alternatives considered:

- Direct live StatsBomb Open download: rejected for v0 because the repo should keep verification no-network and deterministic.
- Heavy plotting/model dependencies such as mplsoccer and trained VAEP pipelines: rejected for v0 because they add dependency and data complexity before a stable event abstraction exists.
- Extending the existing proxy tactical visuals only: rejected because it would not close the true event-data modeling gap.

## Scope

- Add normalized football event entities for passes, shots, carries, and defensive actions.
- Add a local provider that reads StatsBomb-like or simplified JSON event files.
- Build pass-network summaries from completed passes.
- Build xT-lite zone values and per-event spatial value deltas from successful ball progression.
- Build VAEP-lite player contribution summaries with explicit labeling that this is not a trained VAEP model.
- Emit deterministic SVG artifacts for pass network, xT heatmap, and contribution bars.
- Expose the model through CLI JSON/text output and optional artifact writes.

## Guardrails

- No provider network calls in v0.
- No claim of full mplsoccer, xT, or VAEP parity.
- Missing/empty/malformed event data must produce unavailable labels, not fabricated tactical claims.
- Existing fixture snapshot and tactical proxy flows remain unchanged.

## Test Strategy

Use TDD with local JSON fixtures and fake CLI builders. Verify parser normalization, report generation, unavailable-state behavior, SVG file writes, CLI JSON contract, docs, feature registry, graph refresh, and full `scripts/verify.sh`.
