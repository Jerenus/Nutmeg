from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from nutmeg.core.repositories import FixtureRepository
from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.odds import MarketOddsSnapshot, OddsSnapshot
from nutmeg.domain.value import SkippedValueFixture, ValueBoard, ValueCandidate
from nutmeg.models.betting import quarter_kelly_fraction
from nutmeg.models.dixon_coles import (
    DixonColesLiteModel,
    MarketProbabilities,
    expected_goals_from_snapshot,
)


class SnapshotService(Protocol):
    def build_snapshot(self, fixture_id: str, *, recent_matches: int = 5):
        ...


class OddsService(Protocol):
    def build_snapshot(self, fixture_id: str, *, persist_history: bool = True) -> OddsSnapshot:
        ...


class ValueBoardService:
    def __init__(
        self,
        *,
        fixture_repository: FixtureRepository,
        snapshot_service: SnapshotService,
        odds_service: OddsService,
        pricing_model: DixonColesLiteModel | None = None,
    ) -> None:
        self._fixture_repository = fixture_repository
        self._snapshot_service = snapshot_service
        self._odds_service = odds_service
        self._pricing_model = pricing_model or DixonColesLiteModel()

    def build_board(
        self,
        *,
        league: str,
        days: int,
        limit: int = 10,
        min_edge: float = 0.03,
    ) -> ValueBoard:
        fixtures = self._fixture_repository.list_upcoming(league=league, days=days)
        real_fixtures = [fixture for fixture in fixtures if fixture.source != 'demo']
        if real_fixtures:
            fixtures = real_fixtures
        return self._board_from_fixtures(
            fixtures,
            league=league,
            days=days,
            limit=limit,
            min_edge=min_edge,
        )

    def build_board_for_fixtures(
        self,
        fixtures: list[Fixture],
        *,
        min_edge: float = 0.03,
        league: str = 'fixtures',
        days: int = 0,
    ) -> ValueBoard:
        """Evaluate an explicit list of fixtures (model vs odds → edge/EV/Kelly).

        The public bridge entry point: callers that already hold the exact
        fixtures to price (e.g. ``JczqValueBridge`` after aligning JCZQ matches
        to API-Football) skip the league/days repository query entirely. Every
        produced candidate is kept — no top-N truncation — so a per-fixture
        conflict consumer sees the full set. Ranking and per-fixture skip
        handling are identical to ``build_board``.
        """

        # The repo-backed odds/snapshot services resolve fixtures by id. A
        # bridge caller (JczqValueBridge) aligns JCZQ matches to live
        # API-Football fixtures that were never synced into the repo — persist
        # them first so the downstream get_fixture lookup succeeds. Guarded so
        # the explicit-fixture-list path still works with no repository.
        if self._fixture_repository is not None and fixtures:
            self._fixture_repository.upsert_many(list(fixtures))

        return self._board_from_fixtures(
            fixtures,
            league=league,
            days=days,
            limit=None,
            min_edge=min_edge,
        )

    def _board_from_fixtures(
        self,
        fixtures: list[Fixture],
        *,
        league: str,
        days: int,
        limit: int | None,
        min_edge: float,
    ) -> ValueBoard:
        candidates: list[ValueCandidate] = []
        skipped: list[SkippedValueFixture] = []
        for fixture in fixtures:
            try:
                candidates.extend(
                    self._fixture_candidates(
                        fixture,
                        min_edge=min_edge,
                    )
                )
            except Exception as exc:
                skipped.append(self._skipped(fixture, str(exc)))

        ranked = sorted(
            candidates,
            key=lambda candidate: (
                -candidate.edge,
                -candidate.quarter_kelly_fraction,
                candidate.kickoff_at,
                candidate.fixture_id,
            ),
        )
        if limit is not None:
            ranked = ranked[:limit]
        return ValueBoard(
            league=league,
            days=days,
            generated_at=datetime.now(UTC).replace(microsecond=0),
            candidates=ranked,
            skipped=skipped,
        )

    def _fixture_candidates(
        self,
        fixture: Fixture,
        *,
        min_edge: float,
    ) -> list[ValueCandidate]:
        snapshot = self._snapshot_service.build_snapshot(fixture.fixture_id, recent_matches=5)
        model_markets = self._pricing_model.price_markets(
            expected_goals_from_snapshot(snapshot)
        )
        odds = self._odds_service.build_snapshot(fixture.fixture_id, persist_history=False)

        # match_winner is the mandatory anchor: without it the fixture cannot be
        # priced against the market and is skipped entirely.
        match_winner = odds.markets.get('match_winner')
        if match_winner is None or match_winner.status != 'available':
            raise ValueError('match_winner market is unavailable')

        candidates: list[ValueCandidate] = []
        for market_key, model_probabilities in self._market_probabilities(model_markets):
            market = odds.markets.get(market_key)
            if market is None or market.status != 'available':
                # Secondary markets degrade gracefully — only match_winner is
                # mandatory, and that has already been checked above.
                continue
            candidates.extend(
                self._market_candidates(
                    fixture=fixture,
                    odds=odds,
                    market=market,
                    model_probabilities=model_probabilities,
                    model_name=model_markets.model_name,
                    model_source=model_markets.expected_goals_source,
                    min_edge=min_edge,
                )
            )
        return candidates

    def _market_probabilities(
        self,
        model_markets: MarketProbabilities,
    ) -> list[tuple[str, dict[str, float]]]:
        """Flatten the model's market probabilities into (market_key, probs) pairs."""
        markets: list[tuple[str, dict[str, float]]] = [
            ('match_winner', model_markets.match_winner),
            ('total_goals', model_markets.total_goals),
            ('correct_score', model_markets.correct_score),
        ]
        markets.extend(model_markets.handicap.items())
        return markets

    def _market_candidates(
        self,
        *,
        fixture: Fixture,
        odds: OddsSnapshot,
        market: MarketOddsSnapshot,
        model_probabilities: dict[str, float],
        model_name: str,
        model_source: str,
        min_edge: float,
    ) -> list[ValueCandidate]:
        outcome_by_key = {outcome.outcome_key: outcome for outcome in market.outcomes}
        candidates: list[ValueCandidate] = []
        for outcome_key, model_probability in model_probabilities.items():
            outcome = outcome_by_key.get(outcome_key)
            if (
                outcome is None
                or outcome.fair_probability is None
                or outcome.best_odds is None
            ):
                continue
            edge = round(model_probability - outcome.fair_probability, 6)
            expected_value = round((model_probability * outcome.best_odds) - 1, 6)
            if edge < min_edge or expected_value <= 0:
                continue
            if not 0 < model_probability < 1:
                # quarter_kelly_fraction requires a strict probability;
                # degenerate buckets cannot be staked.
                continue
            kelly = round(
                quarter_kelly_fraction(
                    true_probability=model_probability,
                    decimal_odds=outcome.best_odds,
                ),
                6,
            )
            if kelly <= 0:
                continue
            candidates.append(
                self._candidate(
                    fixture=fixture,
                    odds=odds,
                    market=market,
                    outcome_key=outcome_key,
                    outcome_name=outcome.outcome_name,
                    model_probability=model_probability,
                    market_probability=outcome.fair_probability,
                    edge=edge,
                    best_odds=outcome.best_odds,
                    expected_value=expected_value,
                    quarter_kelly_fraction=kelly,
                    model_name=model_name,
                    model_source=model_source,
                )
            )
        return candidates

    def _candidate(
        self,
        *,
        fixture: Fixture,
        odds: OddsSnapshot,
        market: MarketOddsSnapshot,
        outcome_key: str,
        outcome_name: str,
        model_probability: float,
        market_probability: float,
        edge: float,
        best_odds: float,
        expected_value: float,
        quarter_kelly_fraction: float,
        model_name: str,
        model_source: str,
    ) -> ValueCandidate:
        return ValueCandidate(
            fixture_id=fixture.fixture_id,
            kickoff_at=fixture.kickoff_at,
            home_team=fixture.home_team,
            away_team=fixture.away_team,
            outcome_key=outcome_key,
            outcome_name=outcome_name,
            model_probability=model_probability,
            market_probability=market_probability,
            edge=edge,
            best_odds=best_odds,
            expected_value=expected_value,
            quarter_kelly_fraction=quarter_kelly_fraction,
            rating=_value_rating(edge, quarter_kelly_fraction),
            model_name=model_name,
            market_key=market.market_key,
            source_notes=[
                f'model={model_source}',
                f'odds={odds.provider.name}',
                f'market={market.market_key}',
            ],
        )

    def _skipped(self, fixture: Fixture, reason: str) -> SkippedValueFixture:
        return SkippedValueFixture(
            fixture_id=fixture.fixture_id,
            kickoff_at=fixture.kickoff_at,
            home_team=fixture.home_team,
            away_team=fixture.away_team,
            reason=reason,
        )


def _value_rating(edge: float, quarter_kelly_fraction: float) -> str:
    if edge >= 0.08 and quarter_kelly_fraction >= 0.02:
        return 'strong'
    if edge >= 0.03:
        return 'watchlist'
    return 'thin'
