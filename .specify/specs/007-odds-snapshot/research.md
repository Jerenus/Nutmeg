# Research: Odds Snapshot and Fair Probability

## Decision 1: Use API-Football as the first odds provider

- **Decision**: Keep API-Football as the primary odds source for Sprint 1 odds snapshot delivery.
- **Rationale**: The workspace already has a configured API-Football key, the provider shares the same fixture identity flow already used by Nutmeg, and live probing on 2026-04-24 confirmed that `/odds`, `/odds/bookmakers`, and `/odds/bets` are currently working against upcoming EPL fixtures.
- **Alternatives considered**:
  - **The Odds API as primary**: strong bookmaker breadth and historical products, but it introduces a second paid key plus a new event-ID mapping problem before delivering the first usable slice.
  - **OddsPapi as primary**: promising bookmaker breadth, but it would require fresh due diligence and a brand-new mapping layer without helping the current Sprint acceptance path.

## Decision 2: Scope the first fair-probability slice to canonical main markets

- **Decision**: Support match winner, both teams to score, and a standard totals line first; keep the model/provider boundary open for more markets later.
- **Rationale**: These markets cover the first useful operator workflow, are straightforward to normalize into two-way/three-way no-vig calculations, and avoid forcing a rushed handicap-line abstraction before the odds data path is stable.
- **Alternatives considered**:
  - **Normalize every available bet type immediately**: too broad for the first odds slice and likely to hide brittle parsing work under a large surface area.
  - **Support only match winner**: lower risk, but too narrow to qualify as a real odds snapshot for the design intent.

## Decision 3: Keep the odds snapshot on-demand, not historically materialized yet

- **Decision**: Build odds snapshots on demand for a cached fixture and defer historical persistence to a later slice.
- **Rationale**: The user asked for the odds snapshot and fair-probability chain first. On-demand fetch plus structured output validates provider wiring, normalization, and fair math without expanding scope into scheduling and historical storage.
- **Alternatives considered**:
  - **Persist every snapshot immediately**: useful later, but it adds schema, cadence, and storage policy work before the core analysis path is even validated.
  - **Avoid all seams and hardcode API-Football into the CLI**: fastest short-term, but it would create avoidable rewrite pressure as soon as a second provider is introduced.

## Notes from current official/provider evidence

- API-Football's official 2026 guide says `/odds/bookmakers`, `/odds/bets`, and `/odds/live/bets` are reference endpoints that should be cached and used to filter odds queries.
- API-Football live probing on 2026-04-24 returned working bookmaker catalogs, bet catalogs, and a live pre-match odds payload for fixture `1379304`.
- The Odds API official docs currently advertise a broader cross-sport bookmaker footprint, featured `h2h`, `spreads`, and `totals` markets, and paid historical odds snapshots. That makes it a good future secondary provider once Nutmeg needs sharper bookmaker breadth or historical odds movement analysis.
