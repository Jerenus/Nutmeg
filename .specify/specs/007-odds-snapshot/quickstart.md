# Quickstart: Odds Snapshot and Fair Probability

## Goal

Validate that Nutmeg can build a pre-match odds snapshot for a cached fixture and derive fair probabilities from the available bookmaker prices.

## Prerequisites

- `.env` contains `NUTMEG_API_FOOTBALL_KEY`
- optional secondary-provider validation also needs `NUTMEG_THE_ODDS_API_KEY`
- upcoming fixtures have already been synced, for example:
  - `uv run nutmeg fixtures-sync --league epl --days 14`

## Happy-path checks

1. Fetch a JSON odds snapshot for a real fixture:
   - `uv run nutmeg odds-snapshot --fixture-id 1379304 --format json`
2. Confirm the response includes:
   - fixture metadata
   - source/provider update metadata
   - supported markets
   - fair probabilities that sum to one for complete markets
3. Fetch the text rendering:
   - `uv run nutmeg odds-snapshot --fixture-id 1379304`
4. Confirm the text view clearly separates:
   - raw bookmaker prices
   - derived fair probabilities / fair odds
   - unavailable markets

## Secondary-provider checks

1. Validate the reconciliation-backed The Odds API path:
   - `NUTMEG_ODDS_PROVIDER=the-odds-api uv run nutmeg odds-snapshot --fixture-id 1379304 --format json`
2. Confirm the response still uses the same consumer contract while reporting:
   - `provider.name = "the-odds-api"`
   - canonical market keys such as `match_winner`, `btts`, and standard totals
   - no fabricated fixture match if reconciliation cannot find an event

## Failure-path checks

1. Unknown fixture:
   - `uv run nutmeg odds-snapshot --fixture-id does-not-exist`
2. Provider missing:
   - run with `NUTMEG_API_FOOTBALL_KEY` unset in a clean environment and confirm the command fails clearly
3. No odds yet:
   - run against a synced fixture with no upstream odds and confirm the response stays explicit rather than ambiguous
4. Secondary-provider reconciliation miss:
   - run with `NUTMEG_ODDS_PROVIDER=the-odds-api` against a fixture that cannot be matched upstream and confirm the command fails with an explicit reconciliation message

## Verification

- `uv run ruff check .`
- `uv run pytest`
- `python3 -m compileall nutmeg`
- `bash scripts/verify.sh`
