from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.odds import (
    MarketOddsSnapshot,
    OddsProviderSnapshot,
    OddsSnapshot,
    OutcomeOddsSnapshot,
)
from nutmeg.domain.snapshot import (
    FixtureSnapshot,
    MatchupTrendContext,
    TeamEnrichment,
    TeamTrendSummary,
)
from nutmeg.services.value import ValueBoardService


def _fixture(fixture_id: str = 'fx-1') -> Fixture:
    return Fixture(
        fixture_id=fixture_id,
        league_code='epl',
        provider_league_id=39,
        season=2025,
        kickoff_at=datetime(2026, 4, 25, 15, 0, tzinfo=UTC),
        home_team_id=1,
        away_team_id=2,
        home_team='Arsenal',
        away_team='Tottenham Hotspur',
        source='test',
        status=FixtureStatus.SCHEDULED,
    )


def _team(name: str) -> TeamEnrichment:
    return TeamEnrichment(
        canonical_name=name,
        source_names={},
        season_metrics=None,
        recent_form=None,
        shot_summary=None,
        market_value=None,
        injuries=[],
        lineup=None,
    )


def _snapshot(fixture: Fixture) -> FixtureSnapshot:
    return FixtureSnapshot(
        fixture=fixture,
        home=_team(fixture.home_team),
        away=_team(fixture.away_team),
        deferred_sections=[],
        generated_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        matchup=MatchupTrendContext(
            head_to_head=None,
            home_split=None,
            away_split=None,
            home_trend=TeamTrendSummary(
                sample_size=5,
                goals_for_per_match=2.3,
                xg_for_per_match=2.2,
                goals_against_per_match=0.8,
                xg_against_per_match=0.7,
                set_piece_shot_share=None,
                source='test',
            ),
            away_trend=TeamTrendSummary(
                sample_size=5,
                goals_for_per_match=0.9,
                xg_for_per_match=0.9,
                goals_against_per_match=2.0,
                xg_against_per_match=1.9,
                set_piece_shot_share=None,
                source='test',
            ),
        ),
    )


def _odds(fixture: Fixture, *, market_status: str = 'available') -> OddsSnapshot:
    outcomes = []
    if market_status == 'available':
        outcomes = [
            OutcomeOddsSnapshot(
                outcome_key='home',
                outcome_name='Home',
                bookmaker_quotes=[],
                best_odds=2.2,
                average_odds=2.1,
                fair_probability=0.45,
                fair_odds=2.222,
                bookmaker_count=2,
            ),
            OutcomeOddsSnapshot(
                outcome_key='draw',
                outcome_name='Draw',
                bookmaker_quotes=[],
                best_odds=3.6,
                average_odds=3.5,
                fair_probability=0.28,
                fair_odds=3.571,
                bookmaker_count=2,
            ),
            OutcomeOddsSnapshot(
                outcome_key='away',
                outcome_name='Away',
                bookmaker_quotes=[],
                best_odds=4.2,
                average_odds=4.0,
                fair_probability=0.27,
                fair_odds=3.704,
                bookmaker_count=2,
            ),
        ]
    return OddsSnapshot(
        fixture=fixture,
        provider=OddsProviderSnapshot(
            name='test-odds',
            updated_at=datetime(2026, 4, 25, 8, 0, tzinfo=UTC),
            bookmaker_count=2,
        ),
        markets={
            'match_winner': MarketOddsSnapshot(
                market_key='match_winner',
                market_name='Match Winner',
                status=market_status,
                line=None,
                source_market_ids=[1],
                outcomes=outcomes,
            )
        },
        deferred_sections=[],
    )


class FakeFixtureRepository:
    def __init__(self, fixtures: list[Fixture]) -> None:
        self._fixtures = fixtures

    def list_upcoming(self, league: str, days: int) -> list[Fixture]:
        assert league == 'epl'
        assert days == 3
        return self._fixtures


class FakeSnapshotService:
    def __init__(self, snapshots: dict[str, FixtureSnapshot]) -> None:
        self._snapshots = snapshots
        self.requested_fixture_ids: list[str] = []

    def build_snapshot(self, fixture_id: str, *, recent_matches: int = 5) -> FixtureSnapshot:
        assert recent_matches == 5
        self.requested_fixture_ids.append(fixture_id)
        return self._snapshots[fixture_id]


class FakeOddsService:
    def __init__(self, snapshots: dict[str, OddsSnapshot]) -> None:
        self._snapshots = snapshots
        self.requested_fixture_ids: list[str] = []

    def build_snapshot(self, fixture_id: str, *, persist_history: bool = True) -> OddsSnapshot:
        assert persist_history is False
        self.requested_fixture_ids.append(fixture_id)
        return self._snapshots[fixture_id]


def test_value_board_ranks_positive_model_edge_with_kelly_size() -> None:
    fixture = _fixture()
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _odds(fixture)}),
    )

    board = service.build_board(league='epl', days=3, limit=5, min_edge=0.03)

    assert board.league == 'epl'
    assert board.candidates
    candidate = board.candidates[0]
    assert candidate.fixture_id == fixture.fixture_id
    assert candidate.outcome_key == 'home'
    assert candidate.model_probability > candidate.market_probability
    assert candidate.edge >= 0.03
    assert candidate.best_odds == 2.2
    assert candidate.expected_value > 0
    assert candidate.quarter_kelly_fraction > 0
    assert candidate.rating in {'watchlist', 'strong'}
    assert board.skipped == []


def test_value_board_skips_fixture_without_available_match_winner_market() -> None:
    fixture = _fixture()
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService(
            {fixture.fixture_id: _odds(fixture, market_status='unavailable')}
        ),
    )

    board = service.build_board(league='epl', days=3, limit=5, min_edge=0.03)

    assert board.candidates == []
    assert board.skipped[0].fixture_id == fixture.fixture_id
    assert 'match_winner' in board.skipped[0].reason


def test_value_board_ignores_demo_cache_when_real_fixtures_exist() -> None:
    demo_fixture = replace(_fixture('epl-002'), source='demo', provider_league_id=0)
    real_fixture = replace(
        _fixture('1379305'),
        source='api-football',
        home_team='Manchester United',
        away_team='Brentford',
    )
    snapshot_service = FakeSnapshotService({real_fixture.fixture_id: _snapshot(real_fixture)})
    odds_service = FakeOddsService({real_fixture.fixture_id: _odds(real_fixture)})
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([demo_fixture, real_fixture]),
        snapshot_service=snapshot_service,
        odds_service=odds_service,
    )

    board = service.build_board(league='epl', days=3, limit=5, min_edge=0.03)

    assert snapshot_service.requested_fixture_ids == ['1379305']
    assert odds_service.requested_fixture_ids == ['1379305']
    assert all(item.fixture_id != 'epl-002' for item in board.skipped)
