from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nutmeg.agents.router import QueryIntent
from nutmeg.domain.fixtures import Fixture
from nutmeg.domain.odds import (
    BookmakerQuote,
    HistoricalMarketPoint,
    HistoricalMarketSummary,
    MarketOddsSnapshot,
    OddsProviderSnapshot,
    OddsSnapshot,
    OutcomeOddsSnapshot,
)
from nutmeg.domain.snapshot import (
    AvailabilityContext,
    BenchDepthContext,
    FixtureSnapshot,
    HeadToHeadSummary,
    MatchupTrendContext,
    TeamEnrichment,
    TeamLineup,
    TeamMarketValue,
    TeamSplitSummary,
    TeamTrendSummary,
    snapshot_timestamp,
)
from nutmeg.services.analysis import AnalysisService, InsufficientEvidenceError


def _fixture() -> Fixture:
    return Fixture(
        fixture_id='epl-001',
        league_code='epl',
        season=2025,
        provider_league_id=39,
        kickoff_at=datetime(2026, 4, 26, 15, 30, tzinfo=UTC),
        home_team='Arsenal',
        away_team='Tottenham Hotspur',
        home_team_id=42,
        away_team_id=47,
        venue='Emirates Stadium',
        status_short='NS',
    )


def _team(
    name: str,
    *,
    market_value: int,
    absences: str | None,
    formation: str | None = '4-3-3',
    bench_label: str = 'strong',
) -> TeamEnrichment:
    return TeamEnrichment(
        canonical_name=name,
        source_names={'fbref': name},
        season_metrics=None,
        recent_form=None,
        shot_summary=None,
        market_value=TeamMarketValue(
            source='transfermarkt-datasets',
            total_market_value_eur=market_value,
            top_players=[],
        ),
        injuries=[],
        lineup=TeamLineup(
            status='projected',
            source='transfermarkt-datasets',
            formation=formation,
            players=[],
        ) if formation else None,
        availability=AvailabilityContext(
            injuries=[],
            suspensions=[],
            returning_players=[],
            expected_absences_summary=absences,
            bench_depth=BenchDepthContext(
                bench_market_value_eur=None,
                available_players=7,
                label=bench_label,
                source='transfermarkt-datasets',
            ),
        ),
    )


def _matchup_context() -> MatchupTrendContext:
    return MatchupTrendContext(
        head_to_head=HeadToHeadSummary(
            matches=5,
            home_wins=3,
            draws=1,
            away_wins=1,
            source='api-football',
        ),
        home_split=TeamSplitSummary(
            home_points_per_match=2.3,
            away_points_per_match=1.4,
            home_goals_for_per_match=2.0,
            away_goals_for_per_match=1.1,
            source='api-football',
        ),
        away_split=TeamSplitSummary(
            home_points_per_match=1.8,
            away_points_per_match=1.2,
            home_goals_for_per_match=1.7,
            away_goals_for_per_match=1.3,
            source='api-football',
        ),
        home_trend=TeamTrendSummary(
            sample_size=5,
            goals_for_per_match=2.1,
            xg_for_per_match=1.9,
            goals_against_per_match=0.8,
            xg_against_per_match=0.9,
            set_piece_shot_share=0.22,
            source='understat',
        ),
        away_trend=TeamTrendSummary(
            sample_size=5,
            goals_for_per_match=1.2,
            xg_for_per_match=1.1,
            goals_against_per_match=1.7,
            xg_against_per_match=1.6,
            set_piece_shot_share=0.18,
            source='understat',
        ),
    )


def _snapshot(*, contradictory: bool = False, sparse_tactics: bool = False) -> FixtureSnapshot:
    fixture = _fixture()
    home = _team(
        'Arsenal',
        market_value=800000000,
        absences='Only one rotation concern.' if not sparse_tactics else None,
        formation='4-3-3' if not sparse_tactics else None,
        bench_label='strong',
    )
    away = _team(
        'Tottenham Hotspur',
        market_value=650000000 if not contradictory else 850000000,
        absences='Two first-team doubts.' if not sparse_tactics else None,
        formation='4-2-3-1' if not sparse_tactics else None,
        bench_label='thin' if not contradictory else 'strong',
    )
    return FixtureSnapshot(
        fixture=fixture,
        home=home,
        away=away,
        deferred_sections=[],
        generated_at=snapshot_timestamp(),
        environment=None,
        matchup=None if sparse_tactics else _matchup_context(),
    )


def _odds_snapshot(
    *,
    away_leans: bool = False,
    unavailable: bool = False,
    market_moving: bool = False,
    bookmaker_disagreement: bool = False,
) -> OddsSnapshot:
    fixture = _fixture()
    if unavailable:
        market = MarketOddsSnapshot(
            market_key='match_winner',
            market_name='Match Winner',
            status='unavailable',
            line=None,
            source_market_ids=[],
            outcomes=[],
        )
    else:
        market = MarketOddsSnapshot(
            market_key='match_winner',
            market_name='Match Winner',
            status='available',
            line=None,
            source_market_ids=[1],
            outcomes=[
                OutcomeOddsSnapshot(
                    outcome_key='home',
                    outcome_name='Home',
                    bookmaker_quotes=_bookmaker_quotes('home') if bookmaker_disagreement else [],
                    best_odds=2.2 if bookmaker_disagreement else 1.82 if not away_leans else 3.9,
                    average_odds=1.8 if not away_leans else 3.8,
                    fair_probability=0.55 if not away_leans else 0.24,
                    fair_odds=1.818 if not away_leans else 4.167,
                    bookmaker_count=5,
                ),
                OutcomeOddsSnapshot(
                    outcome_key='draw',
                    outcome_name='Draw',
                    bookmaker_quotes=_bookmaker_quotes('draw') if bookmaker_disagreement else [],
                    best_odds=3.8,
                    average_odds=3.7,
                    fair_probability=0.24,
                    fair_odds=4.167,
                    bookmaker_count=5,
                ),
                OutcomeOddsSnapshot(
                    outcome_key='away',
                    outcome_name='Away',
                    bookmaker_quotes=_bookmaker_quotes('away') if bookmaker_disagreement else [],
                    best_odds=4.5 if not away_leans else 1.9,
                    average_odds=4.2 if not away_leans else 1.85,
                    fair_probability=0.21 if not away_leans else 0.51,
                    fair_odds=4.762 if not away_leans else 1.961,
                    bookmaker_count=5,
                ),
            ],
        )
    return OddsSnapshot(
        fixture=fixture,
        provider=OddsProviderSnapshot(
            name='api-football',
            updated_at=fixture.kickoff_at,
            bookmaker_count=5,
        ),
        markets={'match_winner': market},
        deferred_sections=[],
        history=_market_history() if market_moving else {},
    )


def _bookmaker_quotes(outcome_key: str) -> list[BookmakerQuote]:
    prices = {
        'home': [1.55, 1.82, 2.20],
        'draw': [3.55, 3.70, 3.95],
        'away': [3.90, 4.20, 4.55],
    }[outcome_key]
    return [
        BookmakerQuote(
            bookmaker_id=index,
            bookmaker_name=f'Book {index}',
            market_id=1,
            market_name='Match Winner',
            selection_value=outcome_key,
            decimal_odds=price,
            source='test',
        )
        for index, price in enumerate(prices, start=1)
    ]


def _market_history() -> dict[str, HistoricalMarketSummary]:
    points = [
        HistoricalMarketPoint(
            captured_at=datetime(2026, 4, 25, 8, 0, tzinfo=UTC),
            provider='api-football',
            market_key='match_winner',
            line=None,
            outcome_probabilities={'home': 0.48, 'draw': 0.27, 'away': 0.25},
            outcome_fair_odds={},
            outcome_best_odds={},
            bookmaker_count=5,
        ),
        HistoricalMarketPoint(
            captured_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
            provider='api-football',
            market_key='match_winner',
            line=None,
            outcome_probabilities={'home': 0.53, 'draw': 0.25, 'away': 0.22},
            outcome_fair_odds={},
            outcome_best_odds={},
            bookmaker_count=5,
        ),
    ]
    return {
        'match_winner': HistoricalMarketSummary(
            market_key='match_winner',
            line=None,
            points=points,
            drift_vs_current={'home': 0.07, 'draw': -0.03, 'away': -0.04},
            movement='moving',
            movement_span=0.05,
        )
    }


class StubSnapshotService:
    def __init__(self, *, contradictory: bool = False, sparse_tactics: bool = False) -> None:
        self._contradictory = contradictory
        self._sparse_tactics = sparse_tactics

    def build_snapshot(self, fixture_id: str, *, recent_matches: int = 5) -> FixtureSnapshot:
        assert fixture_id == 'epl-001'
        return _snapshot(
            contradictory=self._contradictory,
            sparse_tactics=self._sparse_tactics,
        )


class StubOddsService:
    def __init__(
        self,
        *,
        away_leans: bool = False,
        unavailable: bool = False,
        open_game: bool = True,
        partial_market: bool = False,
        strong_handicap: bool = False,
        market_moving: bool = False,
        bookmaker_disagreement: bool = False,
    ) -> None:
        self._away_leans = away_leans
        self._unavailable = unavailable
        self._open_game = open_game
        self._partial_market = partial_market
        self._strong_handicap = strong_handicap
        self._market_moving = market_moving
        self._bookmaker_disagreement = bookmaker_disagreement

    def build_snapshot(self, fixture_id: str, *, persist_history: bool = True) -> OddsSnapshot:
        assert fixture_id == 'epl-001'
        snapshot = _odds_snapshot(
            away_leans=self._away_leans,
            unavailable=self._unavailable,
            market_moving=self._market_moving,
            bookmaker_disagreement=self._bookmaker_disagreement,
        )
        if self._unavailable:
            return snapshot
        totals_market = MarketOddsSnapshot(
            market_key='totals_2_5',
            market_name='Goals Over/Under',
            status='available' if not self._partial_market else 'unavailable',
            line='2.5',
            source_market_ids=[5] if not self._partial_market else [],
            outcomes=[] if self._partial_market else [
                OutcomeOddsSnapshot(
                    outcome_key='over',
                    outcome_name='Over',
                    bookmaker_quotes=[],
                    best_odds=1.72 if self._open_game else 2.3,
                    average_odds=1.7 if self._open_game else 2.2,
                    fair_probability=0.58 if self._open_game else 0.41,
                    fair_odds=1.724 if self._open_game else 2.439,
                    bookmaker_count=4,
                ),
                OutcomeOddsSnapshot(
                    outcome_key='under',
                    outcome_name='Under',
                    bookmaker_quotes=[],
                    best_odds=2.15 if self._open_game else 1.68,
                    average_odds=2.05 if self._open_game else 1.65,
                    fair_probability=0.42 if self._open_game else 0.59,
                    fair_odds=2.381 if self._open_game else 1.695,
                    bookmaker_count=4,
                ),
            ],
        )
        btts_market = MarketOddsSnapshot(
            market_key='btts',
            market_name='Both Teams Score',
            status='available',
            line=None,
            source_market_ids=[8],
            outcomes=[
                OutcomeOddsSnapshot(
                    outcome_key='yes',
                    outcome_name='Yes',
                    bookmaker_quotes=[],
                    best_odds=1.75 if self._open_game else 2.25,
                    average_odds=1.7 if self._open_game else 2.2,
                    fair_probability=0.57 if self._open_game else 0.43,
                    fair_odds=1.754 if self._open_game else 2.326,
                    bookmaker_count=4,
                ),
                OutcomeOddsSnapshot(
                    outcome_key='no',
                    outcome_name='No',
                    bookmaker_quotes=[],
                    best_odds=2.1 if self._open_game else 1.7,
                    average_odds=2.0 if self._open_game else 1.66,
                    fair_probability=0.43 if self._open_game else 0.57,
                    fair_odds=2.326 if self._open_game else 1.754,
                    bookmaker_count=4,
                ),
            ],
        )
        snapshot.markets['totals_2_5'] = totals_market
        snapshot.markets['btts'] = btts_market
        if self._strong_handicap:
            snapshot.markets['asian_handicap_2_0'] = MarketOddsSnapshot(
                market_key='asian_handicap_2_0',
                market_name='Asian Handicap',
                status='available',
                line='2.0',
                source_market_ids=[13],
                outcomes=[
                    OutcomeOddsSnapshot(
                        outcome_key='home',
                        outcome_name='Home',
                        bookmaker_quotes=[],
                        best_odds=2.70,
                        average_odds=2.65,
                        fair_probability=0.36,
                        fair_odds=2.778,
                        bookmaker_count=4,
                    ),
                    OutcomeOddsSnapshot(
                        outcome_key='away',
                        outcome_name='Away',
                        bookmaker_quotes=[],
                        best_odds=1.52,
                        average_odds=1.50,
                        fair_probability=0.64,
                        fair_odds=1.562,
                        bookmaker_count=4,
                    ),
                ],
            )
        return snapshot


def test_analysis_service_builds_tactical_and_market_judgment() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert result.intent == QueryIntent.DECISIONAL
    assert result.judgment.verdict
    assert result.evidence.tactical_summary
    assert result.evidence.snapshot_summary
    assert result.evidence.odds_summary
    assert result.conflict_state == 'aligned'


def test_analysis_service_marks_sparse_tactics_truthfully() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(sparse_tactics=True),
        odds_service=StubOddsService(unavailable=True),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert any('tactical' in item.lower() for item in result.evidence.caveats)
    assert result.judgment.confidence == 'low'


def test_analysis_service_handles_contradictory_evidence() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(away_leans=True),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert result.conflict_state == 'conflicted'
    assert result.judgment.confidence == 'low'
    assert 'market' in result.judgment.counterargument.lower()


def test_analysis_service_rejects_when_query_is_not_decisional() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(),
    )

    with pytest.raises(InsufficientEvidenceError):
        service.analyze_match('epl-001', query='Show me Arsenal context')


def test_analysis_service_adds_market_shape_for_open_game() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(open_game=True),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert result.evidence.market_shape_summary
    assert any('open game' in item.lower() for item in result.evidence.market_shape_summary)


def test_analysis_service_adds_market_shape_for_low_event_game() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(open_game=False),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert any('lower-event' in item.lower() for item in result.evidence.market_shape_summary)


def test_analysis_service_marks_partial_market_shape_truthfully() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(partial_market=True),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert any('market shape' in item.lower() for item in result.evidence.caveats)


def test_analysis_service_mentions_stronger_handicap_pressure() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(strong_handicap=True),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert any('handicap' in item.lower() for item in result.evidence.market_shape_summary)
    assert any('win by margin' in item.lower() for item in result.evidence.market_shape_summary)

def test_analysis_service_mentions_match_winner_movement() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(market_moving=True),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert any('movement' in item.lower() for item in result.evidence.odds_summary)
    assert any('drift' in item.lower() for item in result.evidence.odds_summary)


def test_analysis_service_caps_confidence_for_bookmaker_disagreement() -> None:
    service = AnalysisService(
        snapshot_service=StubSnapshotService(),
        odds_service=StubOddsService(bookmaker_disagreement=True),
    )

    result = service.analyze_match('epl-001', query='Should I back Arsenal?')

    assert any('bookmaker disagreement' in item.lower() for item in result.evidence.caveats)
    assert result.judgment.confidence == 'medium'
