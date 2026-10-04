from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class BookmakerQuote:
    bookmaker_id: int
    bookmaker_name: str
    market_id: int
    market_name: str
    selection_value: str
    decimal_odds: float
    source: str


@dataclass(slots=True, frozen=True)
class OutcomeOddsSnapshot:
    outcome_key: str
    outcome_name: str
    bookmaker_quotes: list[BookmakerQuote]
    best_odds: float | None = None
    average_odds: float | None = None
    fair_probability: float | None = None
    fair_odds: float | None = None
    bookmaker_count: int = 0


@dataclass(slots=True, frozen=True)
class MarketOddsSnapshot:
    market_key: str
    market_name: str
    status: str
    line: str | None
    source_market_ids: list[int]
    outcomes: list[OutcomeOddsSnapshot]


@dataclass(slots=True, frozen=True)
class OddsProviderSnapshotFeed:
    provider: str
    updated_at: datetime | None
    bookmaker_count: int
    markets: dict[str, MarketOddsSnapshot]


