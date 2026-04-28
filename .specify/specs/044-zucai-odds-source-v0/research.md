# Research: Zucai Odds Source v0

## Decision: Average decimal odds only

**Decision**: v0 parses home/draw/away average decimal odds and optional provider labels.

**Rationale**: `ZucaiWorkflowService` already consumes this shape, and scheduled report recommendations need current evidence more than detailed bookmaker movement in this slice.

**Alternatives considered**:
- Full odds movement history: deferred to a calibration/market movement feature.
- Asian handicap/over-under markets: out of scope for traditional 14-match pool recommendations.

## Decision: Slot-specific registry fields

**Decision**: `afternoon` updates `odds_file`, while `revision` updates `revision_odds_file`.

**Rationale**: 042 already selects revision-specific odds when available. This preserves first-report evidence and decision-confirmation evidence separately.

## Decision: Local-first with explicit live fetch

**Decision**: Source URLs require `--live-fetch`.

**Rationale**: Odds pages are brittle and sometimes rate-limited. Tests and routine operator runs should work from cached local files without surprise network calls.
