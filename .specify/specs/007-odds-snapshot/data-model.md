# Data Model: Odds Snapshot and Fair Probability

## Entities

### OddsSnapshot
- **What it represents**: the full pre-match odds view for one cached fixture.
- **Fields**:
  - `fixture_id`
  - `fixture_kickoff_at`
  - `provider`
  - `provider_updated_at`
  - `bookmaker_count`
  - `markets`
  - `deferred_sections`
- **Validation rules**:
  - must always point to an existing cached fixture
  - provider metadata must be present when odds are available
  - `markets` can be empty only when the provider returned no usable odds

### MarketSnapshot
- **What it represents**: one canonical supported market within the odds snapshot.
- **Fields**:
  - `market_key`
  - `market_name`
  - `status`
  - `line`
  - `source_market_ids`
  - `outcomes`
- **Validation rules**:
  - `status` distinguishes `available`, `incomplete`, and `unavailable`
  - `line` is optional and used only when the market is line-based
  - supported markets must keep a stable output key even if provider naming varies

### OutcomeSnapshot
- **What it represents**: one outcome inside a canonical market.
- **Fields**:
  - `outcome_key`
  - `outcome_name`
  - `bookmaker_quotes`
  - `best_odds`
  - `average_odds`
  - `fair_probability`
  - `fair_odds`
  - `bookmaker_count`
- **Validation rules**:
  - `fair_probability` and `fair_odds` exist only when the market has a complete outcome set
  - `best_odds` is the best decimal price among valid bookmaker quotes for that outcome
  - `average_odds` is derived from valid bookmaker quotes only

### BookmakerQuote
- **What it represents**: one raw bookmaker price used in the canonical market view.
- **Fields**:
  - `bookmaker_id`
  - `bookmaker_name`
  - `market_id`
  - `market_name`
  - `selection_value`
  - `decimal_odds`
- **Validation rules**:
  - decimal odds must be greater than 1
  - duplicate provider rows for the same bookmaker/market/selection should be deduplicated before aggregation

## Relationships

- `OddsSnapshot` contains many `MarketSnapshot` objects.
- `MarketSnapshot` contains many `OutcomeSnapshot` objects.
- `OutcomeSnapshot` contains many `BookmakerQuote` objects.

## Derived rules

- A three-way market produces fair probabilities only when exactly the full outcome set is present.
- A two-way market produces fair probabilities only when both sides of the market are present for the same canonical line.
- Consensus fair probability is derived from bookmaker quotes after margin removal, not from a predictive model.
