# Research: Traditional Zucai 14-Match Workflow v0

## Decision: Structured source snapshots in v0

**Decision**: v0 reads issue, odds, overrides, and outcomes from explicit JSON snapshots.

**Rationale**: The recurring workflow needs determinism, tests, and replayability before live page parsing. Structured snapshots also provide a stable contract for future official/Sina parsers.

**Alternatives considered**:

- Directly parse live websites now: deferred because source layouts and terms can change, and tests would become brittle.
- Store everything in SQLite immediately: deferred because artifact files are enough for owner/private workflow and easier to inspect.

## Decision: Deterministic baseline plus analyst overrides

**Decision**: Generate a baseline recommendation from odds/risk flags, then let valid override picks/rationales replace baseline recommendations.

**Rationale**: Traditional足彩 construction is not a pure single-match model problem; late team news, human risk preference, and pool-level budget matter. Overrides preserve auditability without hard-coding one issue's judgement.

**Alternatives considered**:

- Pure model only: rejected because current Nutmeg does not yet model the whole 14-match pool with enough data coverage.
- Manual picks only: rejected because the reusable workflow needs a baseline and validation.

## Decision: JSON/Markdown source of truth, PDF as delivery rendering

**Decision**: The report payload and Markdown artifact are canonical; PDF is generated for Telegram/user delivery.

**Rationale**: JSON is testable and replayable. Markdown is diffable. PDF is useful for distribution but not ideal as a data store.

**Alternatives considered**:

- PDF only: rejected because grading/calibration would need to reverse-parse a presentation artifact.

## Decision: File-driven grading in v0

**Decision**: `zucai-grade` reads a saved report and outcome JSON rather than introducing a database schema.

**Rationale**: This closes the loop for every issue with minimal infrastructure and keeps future calibration storage optional.

**Alternatives considered**:

- Reuse prediction repository: rejected for v0 because 14-match plans have pool-level coverage semantics different from single match-winner predictions.
