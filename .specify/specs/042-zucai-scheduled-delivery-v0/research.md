# Research: Zucai Scheduled Delivery v0

## Decision: Local registry first

**Decision**: Use a local JSON issue registry for v0 instead of scraping official schedule pages inside the scheduler.

**Rationale**: `041` intentionally made Zucai reports structured-snapshot driven. The scheduler should decide whether to run and pass paths to the existing report builder; parser reliability belongs in a later source-provider feature.

**Alternatives considered**:
- Direct HTML scraping in scheduler: rejected because it would mix scheduling, parsing, and report generation and make tests brittle.
- Hard-code bundled issue ids: rejected because recurring every-issue operation needs a data file that can be updated independently.

## Decision: Two named slots

**Decision**: Support `afternoon` and `revision` only in v0.

**Rationale**: These map exactly to the user's requested 16:00 first analysis and 18:30 decision-confirmation analysis. More arbitrary schedules can be added after real usage proves the need.

**Alternatives considered**:
- Free-form slot names: rejected because duplicate prevention and captions need stable semantics.
- Single rerun command: rejected because first and revision reports must be separately identifiable.

## Decision: JSON run record

**Decision**: Store run attempts in a local JSON file keyed by run date, slot, and issue id.

**Rationale**: The feature only needs duplicate prevention and auditability for a personal operator workflow. A SQLite table is premature until parser/calibration data grows.

**Alternatives considered**:
- No durable record: rejected because duplicate scheduled sends are a material risk.
- Database table: deferred because local JSON is enough and easier to inspect.

## Decision: launchd templates, not automatic install

**Decision**: Ship launchd template files and documentation; do not automatically install or load them.

**Rationale**: Installing a background job that can send Telegram documents is an outbound side effect. The operator should explicitly load the templates after reviewing paths and flags.

**Alternatives considered**:
- Auto-install during implementation: rejected for safety.
- Only document cron commands: rejected because the user is on macOS and launchd provides a repeatable local scheduler.
