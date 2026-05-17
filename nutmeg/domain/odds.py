from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from nutmeg.domain.fixtures import Fixture


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


@runtime_checkable
class OddsProvider(Protocol):
    """Unified surface for an odds-fetch client.

    Both ``ApiFootballClient`` and ``TheOddsApiClient`` conform structurally.
    Call sites (``OddsSnapshotService``, ``build_odds_provider_client``) depend
    on this protocol rather than a concrete class so the configured provider
    (``config.settings.odds_provider``) can be swapped freely.
    """

    def fetch_fixture_odds(self, fixture_id: str) -> OddsProviderSnapshotFeed:
        """Return the normalized market feed for a single cached fixture."""
        ...


@dataclass(slots=True, frozen=True)
class OddsProviderSnapshot:
    name: str
    updated_at: datetime | None
    bookmaker_count: int


@dataclass(slots=True, frozen=True)
class OddsProviderEvent:
    fixture_id: str
    provider: str
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    matched_at: datetime


@dataclass(slots=True, frozen=True)
class HistoricalMarketPoint:
    captured_at: datetime
    provider: str
    market_key: str
    line: str | None
    outcome_probabilities: dict[str, float] = field(default_factory=dict)
    outcome_fair_odds: dict[str, float] = field(default_factory=dict)
    outcome_best_odds: dict[str, float] = field(default_factory=dict)
    bookmaker_count: int = 0


@dataclass(slots=True, frozen=True)
class HistoricalMarketSummary:
    market_key: str
    line: str | None
    points: list[HistoricalMarketPoint]
    drift_vs_current: dict[str, float]
    movement: str | None = None
    movement_span: float | None = None


@dataclass(slots=True, frozen=True)
class OddsSnapshot:
    fixture: Fixture
    provider: OddsProviderSnapshot
    markets: dict[str, MarketOddsSnapshot]
    deferred_sections: list[str]
    history: dict[str, HistoricalMarketSummary] | None = None
