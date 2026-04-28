# Research: Zucai Source Parser v0

## Decision: Parse text anchors, not one DOM

**Decision**: Convert HTML to normalized text lines and parse issue sections by Chinese textual anchors such as `足球彩票胜负游戏（14场和任选9场）第...期`.

**Rationale**: Public schedule pages can change DOM structure. Text anchors are more stable across official-like notices, copied tables, and cached local files.

**Alternatives considered**:
- Hard-code a single DOM table shape: rejected as brittle.
- Require a manually curated CSV: rejected because it does not reduce operator work enough.

## Decision: Generate schedule registry only

**Decision**: 043 generates `*-issue.json` snapshots and registry entries, but not odds snapshots.

**Rationale**: Odds pages have separate structure and freshness semantics. Splitting them keeps the parser reliable and lets 042 already become date-aware.

**Alternatives considered**:
- Parse odds in the same feature: rejected because it would mix issue discovery and market data calibration.

## Decision: Preserve manual registry fields

**Decision**: When refreshing an issue, preserve existing odds/override/revision fields from the prior registry entry.

**Rationale**: Operators may manually maintain odds and override paths until the odds parser exists. Source sync must not erase this work.

**Alternatives considered**:
- Overwrite the registry completely: rejected because it would lose operator-maintained analysis inputs.

## Decision: Live fetch requires explicit flag

**Decision**: `--source-url` requires `--live-fetch`; otherwise the command fails safely.

**Rationale**: Nutmeg's provider design avoids surprise network calls. Local fixtures keep tests deterministic.

**Alternatives considered**:
- Fetch URLs whenever provided: rejected for privacy/reliability and no-surprise-network constraints.
