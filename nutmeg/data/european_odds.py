"""Multi-source European-odds reference adapter.

Provides a thin Protocol so the daily advisor can opportunistically read
Pinnacle / Bet365 / OddsAPI mirrors when credentials are available, and
silently degrades to the no-op implementation in CI/local without keys.

Live providers can subclass `EuropeanOddsReferenceProvider` and supply real
network calls. This file intentionally ships only the schema + no-op so the
generator integration stays deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from nutmeg.domain.jczq_daily import JczqDailyMatch


@dataclass(frozen=True, slots=True)
class EuropeanOddsQuote:
    match_no: str
    bookmaker: str
    pool: str
    pick: str
    price: float


@dataclass(frozen=True, slots=True)
class CrossCheckSignal:
    match_no: str
    pool: str
    pick: str
    sporttery_implied: float
    european_implied: float
    dispersion: float  # std of bookmaker prices
    delta: float       # european_implied - sporttery_implied


class EuropeanOddsReferenceProvider(Protocol):
    """Returns recent European-bookmaker quotes for a given match list."""

    def quotes_for(self, matches: Iterable[JczqDailyMatch]) -> list[EuropeanOddsQuote]: ...


@dataclass(frozen=True, slots=True)
class NoOpEuropeanOddsProvider:
    """Default no-op implementation; emits no quotes."""

    quotes: tuple[EuropeanOddsQuote, ...] = field(default_factory=tuple)

    def quotes_for(
        self, matches: Iterable[JczqDailyMatch]
    ) -> list[EuropeanOddsQuote]:
        match_nos = {match.match_no for match in matches}
        return [quote for quote in self.quotes if quote.match_no in match_nos]


def cross_check_signals(
    sporttery_implied: dict[str, dict[tuple[str, str], float]],
    european_quotes: list[EuropeanOddsQuote],
    *,
    delta_threshold: float = 0.05,
) -> list[CrossCheckSignal]:
    """Compute dispersion + delta vs Sporttery for each pool/pick."""

    # Group quotes by (match, pool, pick)
    grouped: dict[tuple[str, str, str], list[float]] = {}
    for quote in european_quotes:
        grouped.setdefault((quote.match_no, quote.pool, quote.pick), []).append(quote.price)

    signals: list[CrossCheckSignal] = []
    for (match_no, pool, pick), prices in grouped.items():
        if not prices:
            continue
        european_implied = sum(1.0 / price for price in prices if price > 0) / len(prices)
        sporttery_imp = sporttery_implied.get(match_no, {}).get((pool, pick))
        if sporttery_imp is None:
            continue
        delta = european_implied - sporttery_imp
        if abs(delta) < delta_threshold:
            continue
        mean_price = sum(prices) / len(prices)
        variance = sum((p - mean_price) ** 2 for p in prices) / max(1, len(prices))
        dispersion = variance**0.5
        signals.append(
            CrossCheckSignal(
                match_no=match_no,
                pool=pool,
                pick=pick,
                sporttery_implied=sporttery_imp,
                european_implied=european_implied,
                dispersion=dispersion,
                delta=delta,
            )
        )
    signals.sort(key=lambda item: abs(item.delta), reverse=True)
    return signals
