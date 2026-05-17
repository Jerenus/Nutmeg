from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from nutmeg.core.repositories import FixtureRepository, OddsHistoryRepository
from nutmeg.domain.odds import (
    HistoricalMarketSummary,
    MarketOddsSnapshot,
    OddsProviderSnapshot,
    OddsProviderSnapshotFeed,
    OddsSnapshot,
    OutcomeOddsSnapshot,
)
from nutmeg.models.betting import fair_odds, no_vig_probabilities

SUPPORTED_HANDICAP_LINES: tuple[str, ...] = (
    '0.25',
    '0.5',
    '0.75',
    '1.0',
    '1.25',
    '1.5',
    '1.75',
    '2.0',
    '2.25',
    '2.5',
)

# Integer European handicap lines applied to the home tally, shared with the
# Dixon-Coles pricing model. A negative line is a home deficit.
SUPPORTED_GOAL_HANDICAP_LINES: tuple[int, ...] = (-2, -1, 0, 1, 2)

# Total-goals exact buckets: 0..6 plus a 7+ residual tail.
MAX_TOTAL_GOALS_BUCKET: int = 7


def _goal_handicap_suffix(line: int) -> str:
    if line == 0:
        return '0'
    return f"{'minus' if line < 0 else 'plus'}_{abs(line)}"


def _goal_handicap_line_label(line: int) -> str:
    if line == 0:
        return '0'
    return f'{line:+d}'


TOTAL_GOALS_OUTCOMES: tuple[str, ...] = tuple(
    f'total_{count}' for count in range(MAX_TOTAL_GOALS_BUCKET)
) + (f'total_{MAX_TOTAL_GOALS_BUCKET}_plus',)

# A market whose `expected_outcomes` is DYNAMIC_OUTCOMES has an open-ended
# outcome set (e.g. correct score). Consensus is computed over whatever the
# provider supplies; the market is `available` whenever any outcome is priced.
DYNAMIC_OUTCOMES: tuple[str, ...] = ()

EXPECTED_MARKETS: dict[str, tuple[str, tuple[str, ...] | None, str | None]] = {
    'match_winner': ('Match Winner', ('home', 'draw', 'away'), None),
    'btts': ('Both Teams Score', ('yes', 'no'), None),
    'totals_1_5': ('Goals Over/Under', ('over', 'under'), '1.5'),
    'totals_2_5': ('Goals Over/Under', ('over', 'under'), '2.5'),
    'totals_3_5': ('Goals Over/Under', ('over', 'under'), '3.5'),
    'total_goals': ('Exact Goals Number', TOTAL_GOALS_OUTCOMES, None),
    'correct_score': ('Exact Score', None, None),
    **{
        f"asian_handicap_{line.replace('.', '_')}": ('Asian Handicap', ('home', 'away'), line)
        for line in SUPPORTED_HANDICAP_LINES
    },
    **{
        f'handicap_home_{_goal_handicap_suffix(line)}': (
            'Handicap Result',
            ('home', 'draw', 'away'),
            _goal_handicap_line_label(line),
        )
        for line in SUPPORTED_GOAL_HANDICAP_LINES
    },
}


class OddsFixtureNotFoundError(LookupError):
    pass


class OddsProviderClient(Protocol):
    def fetch_fixture_odds(self, fixture_id: str) -> OddsProviderSnapshotFeed:
        ...


class OddsSnapshotService:
    def __init__(
        self,
        *,
        fixture_repository: FixtureRepository,
        odds_client: OddsProviderClient,
        odds_history_repository: OddsHistoryRepository | None = None,
    ) -> None:
        self._fixture_repository = fixture_repository
        self._odds_client = odds_client
        self._odds_history_repository = odds_history_repository

    def build_snapshot(self, fixture_id: str, *, persist_history: bool = True) -> OddsSnapshot:
        fixture = self._fixture_repository.get_fixture(fixture_id)
        if fixture is None:
            raise OddsFixtureNotFoundError(
                f'Fixture `{fixture_id}` was not found in the local cache.'
            )

        provider_feed = self._odds_client.fetch_fixture_odds(fixture_id)
        markets = {
            market_key: self._build_market_snapshot(
                market_key,
                provider_feed.markets.get(market_key),
            )
            for market_key in EXPECTED_MARKETS
        }

        snapshot = OddsSnapshot(
            fixture=fixture,
            provider=OddsProviderSnapshot(
                name=provider_feed.provider,
                updated_at=provider_feed.updated_at,
                bookmaker_count=provider_feed.bookmaker_count,
            ),
            markets=markets,
            deferred_sections=[],
        )
        if self._odds_history_repository is not None and persist_history:
            self._odds_history_repository.append_snapshot(snapshot)
            snapshot = replace(snapshot, history=self._build_history(snapshot))
        return snapshot

    def _build_market_snapshot(
        self,
        market_key: str,
        provider_market: MarketOddsSnapshot | None,
    ) -> MarketOddsSnapshot:
        market_name, expected_outcomes, default_line = EXPECTED_MARKETS[market_key]
        if provider_market is None:
            return MarketOddsSnapshot(
                market_key=market_key,
                market_name=market_name,
                status='unavailable',
                line=default_line,
                source_market_ids=[],
                outcomes=[],
            )

        outcomes = [self._with_price_summary(outcome) for outcome in provider_market.outcomes]
        outcome_by_key = {outcome.outcome_key: outcome for outcome in outcomes}

        # A `None` expected-outcomes set means the market is open-ended (e.g.
        # correct score): use whatever the provider priced, in provider order.
        if expected_outcomes is None:
            resolved_outcomes: tuple[str, ...] = tuple(
                outcome.outcome_key
                for outcome in outcomes
                if outcome.bookmaker_quotes
            )
            complete = bool(resolved_outcomes)
        else:
            resolved_outcomes = expected_outcomes
            complete = all(
                outcome_key in outcome_by_key
                and outcome_by_key[outcome_key].bookmaker_quotes
                for outcome_key in expected_outcomes
            )

        if not complete:
            return MarketOddsSnapshot(
                market_key=provider_market.market_key,
                market_name=provider_market.market_name,
                status='incomplete' if outcomes else 'unavailable',
                line=provider_market.line,
                source_market_ids=provider_market.source_market_ids,
                outcomes=outcomes,
            )

        consensus = self._consensus_probabilities(resolved_outcomes, outcome_by_key)
        enriched = [
            replace(
                outcome_by_key[outcome_key],
                fair_probability=consensus[outcome_key],
                fair_odds=fair_odds(consensus[outcome_key]),
            )
            for outcome_key in resolved_outcomes
        ]
        return MarketOddsSnapshot(
            market_key=provider_market.market_key,
            market_name=provider_market.market_name,
            status='available',
            line=provider_market.line,
            source_market_ids=provider_market.source_market_ids,
            outcomes=enriched,
        )

    def _with_price_summary(self, outcome: OutcomeOddsSnapshot) -> OutcomeOddsSnapshot:
        odds = [quote.decimal_odds for quote in outcome.bookmaker_quotes]
        if not odds:
            return replace(outcome, bookmaker_count=0)
        average = round(sum(odds) / len(odds), 3)
        return replace(
            outcome,
            best_odds=max(odds),
            average_odds=average,
            bookmaker_count=len(odds),
        )

    def _consensus_probabilities(
        self,
        expected_outcomes: tuple[str, ...],
        outcome_by_key: dict[str, OutcomeOddsSnapshot],
    ) -> dict[str, float]:
        bookmaker_prices: dict[int, dict[str, float]] = {}
        for outcome_key in expected_outcomes:
            for quote in outcome_by_key[outcome_key].bookmaker_quotes:
                bookmaker_prices.setdefault(
                    quote.bookmaker_id,
                    {},
                )[outcome_key] = quote.decimal_odds

        consensus: dict[str, list[float]] = {outcome_key: [] for outcome_key in expected_outcomes}
        for prices in bookmaker_prices.values():
            if not all(outcome_key in prices for outcome_key in expected_outcomes):
                continue
            fair_probs = no_vig_probabilities(
                [prices[outcome_key] for outcome_key in expected_outcomes]
            )
            for outcome_key, probability in zip(expected_outcomes, fair_probs, strict=True):
                consensus[outcome_key].append(probability)

        averaged = {
            outcome_key: round(sum(values) / len(values), 6)
            for outcome_key, values in consensus.items()
            if values
        }
        total = sum(averaged.values())
        if total <= 0:
            return averaged
        return {
            outcome_key: round(probability / total, 6)
            for outcome_key, probability in averaged.items()
        }

    def _build_history(self, snapshot: OddsSnapshot) -> dict[str, HistoricalMarketSummary]:
        if self._odds_history_repository is None:
            return {}
        history: dict[str, HistoricalMarketSummary] = {}
        for market_key, market in snapshot.markets.items():
            points = self._odds_history_repository.list_market_history(
                snapshot.fixture.fixture_id,
                market_key=market_key,
                line=market.line,
            )
            current_probs = {
                outcome.outcome_key: outcome.fair_probability
                for outcome in market.outcomes
                if outcome.fair_probability is not None
            }
            drift: dict[str, float] = {}
            if points:
                baseline = points[0]
                for outcome_key, current_probability in current_probs.items():
                    previous = baseline.outcome_probabilities.get(outcome_key)
                    if previous is None:
                        continue
                    drift[outcome_key] = round(current_probability - previous, 6)
            movement = None
            movement_span = None
            if len(points) >= 2:
                earliest = points[0]
                latest = points[-1]
                comparable = [
                    abs(latest.outcome_probabilities[key] - earliest.outcome_probabilities[key])
                    for key in current_probs
                    if key in latest.outcome_probabilities and key in earliest.outcome_probabilities
                ]
                if comparable:
                    movement_span = round(max(comparable), 6)
                    movement = 'flat' if movement_span < 0.01 else 'moving'
            history[market_key] = HistoricalMarketSummary(
                market_key=market_key,
                line=market.line,
                points=points,
                drift_vs_current=drift,
                movement=movement,
                movement_span=movement_span,
            )
        return history
