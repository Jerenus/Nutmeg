from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.domain.fixtures import Fixture, FixtureStatus


def _fixture() -> Fixture:
    return Fixture(
        fixture_id='1234',
        league_code='epl',
        provider_league_id=39,
        season=2025,
        kickoff_at=datetime(2026, 4, 25, 14, 0, tzinfo=UTC),
        home_team_id=40,
        away_team_id=52,
        home_team='Liverpool',
        away_team='Crystal Palace',
        source='api-football',
        status=FixtureStatus.SCHEDULED,
        status_short='NS',
        status_long='Not Started',
        venue='Anfield',
    )


class FakeFixtureRepository:
    def __init__(self, fixture: Fixture | None) -> None:
        self._fixture = fixture

    def get_fixture(self, fixture_id: str) -> Fixture | None:
        if self._fixture is None or self._fixture.fixture_id != fixture_id:
            return None
        return self._fixture


class FakeOddsClient:
    def fetch_fixture_odds(self, fixture_id: str):
        from nutmeg.domain.odds import (
            BookmakerQuote,
            MarketOddsSnapshot,
            OddsProviderSnapshotFeed,
            OutcomeOddsSnapshot,
        )

        assert fixture_id == '1234'
        return OddsProviderSnapshotFeed(
            provider='api-football',
            updated_at=datetime(2026, 4, 24, 6, 16, 30, tzinfo=UTC),
            bookmaker_count=2,
            markets={
                'match_winner': MarketOddsSnapshot(
                    market_key='match_winner',
                    market_name='Match Winner',
                    status='available',
                    line=None,
                    source_market_ids=[1],
                    outcomes=[
                        OutcomeOddsSnapshot(
                            outcome_key='home',
                            outcome_name='Home',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=1,
                                    market_name='Match Winner',
                                    selection_value='Home',
                                    decimal_odds=1.45,
                                    source='api-football',
                                ),
                                BookmakerQuote(
                                    bookmaker_id=6,
                                    bookmaker_name='1xBet',
                                    market_id=1,
                                    market_name='Match Winner',
                                    selection_value='Home',
                                    decimal_odds=1.48,
                                    source='api-football',
                                ),
                            ],
                        ),
                        OutcomeOddsSnapshot(
                            outcome_key='draw',
                            outcome_name='Draw',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=1,
                                    market_name='Match Winner',
                                    selection_value='Draw',
                                    decimal_odds=4.55,
                                    source='api-football',
                                ),
                                BookmakerQuote(
                                    bookmaker_id=6,
                                    bookmaker_name='1xBet',
                                    market_id=1,
                                    market_name='Match Winner',
                                    selection_value='Draw',
                                    decimal_odds=4.40,
                                    source='api-football',
                                ),
                            ],
                        ),
                        OutcomeOddsSnapshot(
                            outcome_key='away',
                            outcome_name='Away',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=1,
                                    market_name='Match Winner',
                                    selection_value='Away',
                                    decimal_odds=6.25,
                                    source='api-football',
                                ),
                                BookmakerQuote(
                                    bookmaker_id=6,
                                    bookmaker_name='1xBet',
                                    market_id=1,
                                    market_name='Match Winner',
                                    selection_value='Away',
                                    decimal_odds=6.10,
                                    source='api-football',
                                ),
                            ],
                        ),
                    ],
                ),
                'totals_1_5': MarketOddsSnapshot(
                    market_key='totals_1_5',
                    market_name='Goals Over/Under',
                    status='available',
                    line='1.5',
                    source_market_ids=[5],
                    outcomes=[
                        OutcomeOddsSnapshot(
                            outcome_key='over',
                            outcome_name='Over',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=5,
                                    market_name='Goals Over/Under',
                                    selection_value='Over 1.5',
                                    decimal_odds=1.18,
                                    source='api-football',
                                )
                            ],
                        )
                    ],
                ),
                'totals_2_5': MarketOddsSnapshot(
                    market_key='totals_2_5',
                    market_name='Goals Over/Under',
                    status='available',
                    line='2.5',
                    source_market_ids=[5],
                    outcomes=[
                        OutcomeOddsSnapshot(
                            outcome_key='over',
                            outcome_name='Over',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=5,
                                    market_name='Goals Over/Under',
                                    selection_value='Over 2.5',
                                    decimal_odds=1.57,
                                    source='api-football',
                                )
                            ],
                        )
                    ],
                ),
                'asian_handicap_0_5': MarketOddsSnapshot(
                    market_key='asian_handicap_0_5',
                    market_name='Asian Handicap',
                    status='available',
                    line='0.5',
                    source_market_ids=[13],
                    outcomes=[
                        OutcomeOddsSnapshot(
                            outcome_key='home',
                            outcome_name='Home',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=13,
                                    market_name='Asian Handicap',
                                    selection_value='Home -0.5',
                                    decimal_odds=1.92,
                                    source='api-football',
                                )
                            ],
                        ),
                        OutcomeOddsSnapshot(
                            outcome_key='away',
                            outcome_name='Away',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=13,
                                    market_name='Asian Handicap',
                                    selection_value='Away +0.5',
                                    decimal_odds=1.94,
                                    source='api-football',
                                )
                            ],
                        ),
                    ],
                ),
                'asian_handicap_2_0': MarketOddsSnapshot(
                    market_key='asian_handicap_2_0',
                    market_name='Asian Handicap',
                    status='available',
                    line='2.0',
                    source_market_ids=[13],
                    outcomes=[
                        OutcomeOddsSnapshot(
                            outcome_key='home',
                            outcome_name='Home',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=13,
                                    market_name='Asian Handicap',
                                    selection_value='Home -2',
                                    decimal_odds=2.70,
                                    source='api-football',
                                )
                            ],
                        ),
                        OutcomeOddsSnapshot(
                            outcome_key='away',
                            outcome_name='Away',
                            bookmaker_quotes=[
                                BookmakerQuote(
                                    bookmaker_id=1,
                                    bookmaker_name='10Bet',
                                    market_id=13,
                                    market_name='Asian Handicap',
                                    selection_value='Away +2',
                                    decimal_odds=1.48,
                                    source='api-football',
                                )
                            ],
                        ),
                    ],
                ),
            },
        )


class EmptyOddsClient:
    def fetch_fixture_odds(self, fixture_id: str):
        from nutmeg.domain.odds import OddsProviderSnapshotFeed

        assert fixture_id == '1234'
        return OddsProviderSnapshotFeed(
            provider='api-football',
            updated_at=None,
            bookmaker_count=0,
            markets={},
        )


class InMemoryOddsHistoryRepository:
    def __init__(self) -> None:
        self._points = []

    def append_snapshot(self, snapshot) -> None:
        captured_at = snapshot.provider.updated_at
        for market in snapshot.markets.values():
            self._points.append(
                {
                    'captured_at': captured_at,
                    'provider': snapshot.provider.name,
                    'market_key': market.market_key,
                    'line': market.line,
                    'bookmaker_count': snapshot.provider.bookmaker_count,
                    'outcome_probabilities': {
                        outcome.outcome_key: outcome.fair_probability
                        for outcome in market.outcomes
                        if outcome.fair_probability is not None
                    },
                    'outcome_fair_odds': {
                        outcome.outcome_key: outcome.fair_odds
                        for outcome in market.outcomes
                        if outcome.fair_odds is not None
                    },
                    'outcome_best_odds': {
                        outcome.outcome_key: outcome.best_odds
                        for outcome in market.outcomes
                        if outcome.best_odds is not None
                    },
                }
            )

    def list_market_history(
        self,
        fixture_id: str,
        *,
        market_key: str,
        line: str | None,
        limit: int = 20,
    ):
        from nutmeg.domain.odds import HistoricalMarketPoint

        del fixture_id
        points = [
            HistoricalMarketPoint(
                captured_at=item['captured_at'],
                provider=item['provider'],
                market_key=item['market_key'],
                line=item['line'],
                outcome_probabilities=item['outcome_probabilities'],
                outcome_fair_odds=item['outcome_fair_odds'],
                outcome_best_odds=item['outcome_best_odds'],
                bookmaker_count=item['bookmaker_count'],
            )
            for item in self._points
            if item['market_key'] == market_key and item['line'] == line
        ]
        return points[-limit:]


def test_odds_snapshot_service_builds_fair_probabilities_and_marks_incomplete_market() -> None:
    from nutmeg.services.odds import OddsSnapshotService

    service = OddsSnapshotService(
        fixture_repository=FakeFixtureRepository(_fixture()),
        odds_client=FakeOddsClient(),
    )

    snapshot = service.build_snapshot('1234')

    assert snapshot.fixture.fixture_id == '1234'
    assert snapshot.provider.name == 'api-football'
    assert snapshot.provider.bookmaker_count == 2

    match_winner = snapshot.markets['match_winner']
    assert match_winner.status == 'available'
    home = next(outcome for outcome in match_winner.outcomes if outcome.outcome_key == 'home')
    assert home.best_odds == 1.48
    assert home.average_odds == 1.465
    assert home.fair_probability is not None
    assert home.fair_odds is not None
    assert (
        round(sum(outcome.fair_probability or 0.0 for outcome in match_winner.outcomes), 6)
        == 1.0
    )

    early_totals = snapshot.markets['totals_1_5']
    assert early_totals.status == 'incomplete'
    assert early_totals.outcomes[0].fair_probability is None

    totals = snapshot.markets['totals_2_5']
    assert totals.status == 'incomplete'
    assert totals.outcomes[0].fair_probability is None

    asian = snapshot.markets['asian_handicap_0_5']
    assert asian.status == 'available'
    assert round(sum(outcome.fair_probability or 0.0 for outcome in asian.outcomes), 6) == 1.0

    strong_asian = snapshot.markets['asian_handicap_2_0']
    assert strong_asian.status == 'available'
    assert (
        round(sum(outcome.fair_probability or 0.0 for outcome in strong_asian.outcomes), 6)
        == 1.0
    )


def test_odds_snapshot_service_marks_missing_provider_markets_as_unavailable() -> None:
    from nutmeg.services.odds import OddsSnapshotService

    service = OddsSnapshotService(
        fixture_repository=FakeFixtureRepository(_fixture()),
        odds_client=EmptyOddsClient(),
    )

    snapshot = service.build_snapshot('1234')

    assert snapshot.provider.bookmaker_count == 0
    assert snapshot.markets['match_winner'].status == 'unavailable'
    assert snapshot.markets['btts'].status == 'unavailable'
    assert snapshot.markets['totals_1_5'].status == 'unavailable'
    assert snapshot.markets['totals_2_5'].status == 'unavailable'
    assert snapshot.markets['totals_3_5'].status == 'unavailable'
    assert snapshot.markets['asian_handicap_0_5'].status == 'unavailable'
    assert snapshot.markets['asian_handicap_2_0'].status == 'unavailable'


def test_odds_snapshot_service_raises_for_unknown_fixture() -> None:
    from nutmeg.services.odds import OddsFixtureNotFoundError, OddsSnapshotService

    service = OddsSnapshotService(
        fixture_repository=FakeFixtureRepository(None),
        odds_client=FakeOddsClient(),
    )

    with pytest.raises(OddsFixtureNotFoundError, match='missing-001'):
        service.build_snapshot('missing-001')


def test_odds_snapshot_service_builds_history_movement_and_market_drift() -> None:
    from nutmeg.services.odds import OddsSnapshotService

    history_repository = InMemoryOddsHistoryRepository()
    service = OddsSnapshotService(
        fixture_repository=FakeFixtureRepository(_fixture()),
        odds_client=FakeOddsClient(),
        odds_history_repository=history_repository,
    )

    first = service.build_snapshot('1234')
    second = service.build_snapshot('1234')

    assert first.history is not None
    assert second.history is not None
    match_winner_history = second.history['match_winner']
    assert len(match_winner_history.points) == 2
    assert match_winner_history.movement == 'flat'
    assert match_winner_history.movement_span == 0.0
    assert 'home' in match_winner_history.drift_vs_current
    assert match_winner_history.drift_vs_current['home'] == 0.0


def test_build_odds_provider_client_selects_api_football_by_default() -> None:
    from nutmeg.interfaces.cli import build_odds_provider_client

    settings = AppSettings()
    client = build_odds_provider_client(settings)

    assert client.__class__.__name__ == 'ApiFootballClient'


def test_build_odds_provider_client_selects_the_odds_api_when_configured() -> None:
    from nutmeg.interfaces.cli import build_odds_provider_client

    settings = AppSettings(
        odds_provider='the-odds-api',
        the_odds_api_key='demo-key',
    )
    client = build_odds_provider_client(settings)

    assert client.__class__.__name__ == 'TheOddsApiClient'


def test_build_odds_provider_client_rejects_unknown_provider() -> None:
    from nutmeg.interfaces.cli import build_odds_provider_client

    settings = AppSettings(odds_provider='unknown-provider')

    with pytest.raises(ValueError, match='Unsupported odds provider'):
        build_odds_provider_client(settings)
