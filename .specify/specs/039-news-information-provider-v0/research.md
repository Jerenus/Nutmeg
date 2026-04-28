# Research: News Information Provider v0

## Decision: Local JSON plus RSS/Atom-style parsing

**Decision**: v0 supports deterministic JSON files and local RSS/Atom XML files. It does not fetch network sources.

**Rationale**: JSON gives stable tests and explicit reliability labels. RSS/Atom parsing validates the future provider shape without coupling to one paid API or website. No-network behavior preserves the current verification philosophy.

**Alternatives considered**:

- Direct web scraping: rejected due source legality, brittle HTML, robots/copyright concerns, and test instability.
- Paid news/sports API: rejected until the normalized digest contract is stable.
- Only JSON fixtures: rejected because RSS/Atom source shape is likely for future live feeds.

## Decision: Source-driven reliability labels

**Decision**: Reliability labels are `official`, `credible`, `rumor`, and `unverified`. The provider preserves and displays labels rather than inferring confirmation from text.

**Rationale**: Betting-analysis assistance must avoid upgrading rumors into facts. Source-driven labels keep truthfulness visible.

**Alternatives considered**:

- Auto-classify rumor vs confirmed: rejected for v0 because it would require NLP/source policy work.
- Treat all items equally: rejected because rumor/official distinction matters to betting analysis.

## Decision: Client integration via existing information provider seam

**Decision**: `FixtureInformationService.build_information(fixture_id)` returns a client-compatible payload consumed by `ClientService.match_workspace()`.

**Rationale**: The client already has an information provider seam. Reusing it avoids duplicating match-workspace logic and preserves existing service boundaries.

**Alternatives considered**:

- Build information directly inside `ClientService`: rejected because parsing/provider logic belongs in a separate service.
- Add a database table now: rejected because v0 uses local files and no persistent mutation.
