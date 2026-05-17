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
from nutmeg.services.value import _STRENGTH_WINDOW_MATCHES, ValueBoardService


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


def _market(
    market_key: str,
    market_name: str,
    outcomes: list[OutcomeOddsSnapshot],
    *,
    status: str = 'available',
    line: str | None = None,
) -> MarketOddsSnapshot:
    return MarketOddsSnapshot(
        market_key=market_key,
        market_name=market_name,
        status=status,
        line=line,
        source_market_ids=[],
        outcomes=outcomes,
    )


def _priced_outcome(
    outcome_key: str,
    outcome_name: str,
    *,
    fair_probability: float,
    best_odds: float,
) -> OutcomeOddsSnapshot:
    return OutcomeOddsSnapshot(
        outcome_key=outcome_key,
        outcome_name=outcome_name,
        bookmaker_quotes=[],
        best_odds=best_odds,
        average_odds=round(best_odds * 0.97, 3),
        fair_probability=fair_probability,
        fair_odds=round(1.0 / fair_probability, 3),
        bookmaker_count=2,
    )


def _multi_market_odds(fixture: Fixture) -> OddsSnapshot:
    """An odds snapshot covering all four Phase 3a markets.

    Each non-match-winner market deliberately under-prices one model-favoured
    outcome so the value engine surfaces an edge there.
    """
    base = _odds(fixture)
    markets = dict(base.markets)
    markets['total_goals'] = _market(
        'total_goals',
        'Exact Goals Number',
        [
            _priced_outcome('total_0', '0', fair_probability=0.30, best_odds=3.6),
            _priced_outcome('total_1', '1', fair_probability=0.25, best_odds=4.2),
            _priced_outcome('total_2', '2', fair_probability=0.15, best_odds=7.5),
            _priced_outcome('total_3', '3', fair_probability=0.12, best_odds=9.0),
            _priced_outcome('total_4', '4', fair_probability=0.08, best_odds=13.0),
            _priced_outcome('total_5', '5', fair_probability=0.05, best_odds=20.0),
            _priced_outcome('total_6', '6', fair_probability=0.03, best_odds=34.0),
            _priced_outcome('total_7_plus', '7+', fair_probability=0.02, best_odds=50.0),
        ],
    )
    markets['correct_score'] = _market(
        'correct_score',
        'Exact Score',
        [
            _priced_outcome('score_1_0', '1:0', fair_probability=0.05, best_odds=22.0),
            _priced_outcome('score_2_0', '2:0', fair_probability=0.05, best_odds=22.0),
            _priced_outcome('score_2_1', '2:1', fair_probability=0.05, best_odds=22.0),
            _priced_outcome('score_0_0', '0:0', fair_probability=0.85, best_odds=1.15),
        ],
    )
    markets['handicap_home_minus_1'] = _market(
        'handicap_home_minus_1',
        'Handicap Result',
        [
            _priced_outcome('home', 'Home', fair_probability=0.25, best_odds=4.5),
            _priced_outcome('draw', 'Draw', fair_probability=0.40, best_odds=2.6),
            _priced_outcome('away', 'Away', fair_probability=0.35, best_odds=3.0),
        ],
        line='-1',
    )
    return replace(base, markets=markets)


class FakeFixtureRepository:
    def __init__(self, fixtures: list[Fixture]) -> None:
        self._fixtures = fixtures
        self.upserted: list[Fixture] = []

    def list_upcoming(self, league: str, days: int) -> list[Fixture]:
        assert league == 'epl'
        assert days == 3
        return self._fixtures

    def upsert_many(self, fixtures: list[Fixture]) -> int:
        self.upserted.extend(fixtures)
        return len(fixtures)


class FakeSnapshotService:
    def __init__(self, snapshots: dict[str, FixtureSnapshot]) -> None:
        self._snapshots = snapshots
        self.requested_fixture_ids: list[str] = []

    def build_snapshot(self, fixture_id: str, *, recent_matches: int = 5) -> FixtureSnapshot:
        assert recent_matches == _STRENGTH_WINDOW_MATCHES
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


def test_value_board_match_winner_candidate_carries_market_key() -> None:
    fixture = _fixture()
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _odds(fixture)}),
    )

    board = service.build_board(league='epl', days=3, limit=5, min_edge=0.03)

    assert board.candidates
    home = next(c for c in board.candidates if c.outcome_key == 'home')
    assert home.market_key == 'match_winner'


def test_value_board_evaluates_total_goals_market() -> None:
    fixture = _fixture()
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _multi_market_odds(fixture)}),
    )

    board = service.build_board(league='epl', days=3, limit=50, min_edge=0.03)

    total_goals = [c for c in board.candidates if c.market_key == 'total_goals']
    assert total_goals, 'expected at least one total_goals value candidate'
    for candidate in total_goals:
        assert candidate.outcome_key.startswith('total_')
        assert candidate.edge >= 0.03
        assert candidate.expected_value > 0
        assert candidate.quarter_kelly_fraction > 0


def test_value_board_evaluates_correct_score_market() -> None:
    fixture = _fixture()
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _multi_market_odds(fixture)}),
    )

    board = service.build_board(league='epl', days=3, limit=50, min_edge=0.03)

    correct_score = [c for c in board.candidates if c.market_key == 'correct_score']
    assert correct_score, 'expected at least one correct_score value candidate'
    for candidate in correct_score:
        assert candidate.outcome_key.startswith('score_')
        assert candidate.edge >= 0.03


def test_value_board_evaluates_handicap_market() -> None:
    fixture = _fixture()
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _multi_market_odds(fixture)}),
    )

    board = service.build_board(league='epl', days=3, limit=50, min_edge=0.03)

    handicap = [c for c in board.candidates if c.market_key == 'handicap_home_minus_1']
    assert handicap, 'expected at least one handicap value candidate'
    for candidate in handicap:
        assert candidate.outcome_key in {'home', 'draw', 'away'}
        assert candidate.edge >= 0.03


def test_value_board_still_skips_when_match_winner_market_unavailable() -> None:
    fixture = _fixture()
    odds = _multi_market_odds(fixture)
    markets = dict(odds.markets)
    markets['match_winner'] = _market(
        'match_winner', 'Match Winner', [], status='unavailable'
    )
    odds = replace(odds, markets=markets)
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: odds}),
    )

    board = service.build_board(league='epl', days=3, limit=50, min_edge=0.03)

    assert board.candidates == []
    assert board.skipped[0].fixture_id == fixture.fixture_id
    assert 'match_winner' in board.skipped[0].reason


def test_value_board_tolerates_missing_secondary_markets() -> None:
    # Only match_winner is priced; the other markets are simply absent.
    fixture = _fixture()
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _odds(fixture)}),
    )

    board = service.build_board(league='epl', days=3, limit=50, min_edge=0.03)

    assert board.skipped == []
    assert {c.market_key for c in board.candidates} == {'match_winner'}


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


# --- build_board_for_fixtures (Phase 3 piece 1) -----------------------------


def test_build_board_for_fixtures_evaluates_supplied_fixtures() -> None:
    # The bridge entry point: evaluate an explicit list of fixtures without a
    # league/days repository query.
    fixture = _fixture('1379305')
    service = ValueBoardService(
        # No repository needed — fixtures are passed directly.
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _odds(fixture)}),
    )

    board = service.build_board_for_fixtures([fixture], min_edge=0.03)

    assert board.candidates
    assert board.candidates[0].fixture_id == '1379305'
    assert board.candidates[0].edge >= 0.03


def test_build_board_for_fixtures_persists_supplied_fixtures_to_repository() -> None:
    # The repo-backed odds/snapshot services resolve fixtures by id. Callers
    # like JczqValueBridge align JCZQ matches to live API-Football fixtures
    # that were never synced into the repo — build_board_for_fixtures must
    # persist them first or the downstream get_fixture lookup fails.
    fixture = _fixture('1379305')
    repo = FakeFixtureRepository([])  # fixture is NOT pre-synced
    service = ValueBoardService(
        fixture_repository=repo,
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _odds(fixture)}),
    )

    service.build_board_for_fixtures([fixture], min_edge=0.03)

    assert repo.upserted == [fixture]


def test_build_board_for_fixtures_empty_input_returns_empty_board() -> None:
    service = ValueBoardService(
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=FakeSnapshotService({}),
        odds_service=FakeOddsService({}),
    )

    board = service.build_board_for_fixtures([], min_edge=0.03)

    assert board.candidates == []
    assert board.skipped == []


def test_build_board_for_fixtures_keeps_every_candidate() -> None:
    # No top-N truncation: a bridge consumer needs all conflicts per fixture.
    fixture = _fixture('1379305')
    service = ValueBoardService(
        fixture_repository=FakeFixtureRepository([fixture]),
        snapshot_service=FakeSnapshotService({fixture.fixture_id: _snapshot(fixture)}),
        odds_service=FakeOddsService({fixture.fixture_id: _multi_market_odds(fixture)}),
    )

    full = service.build_board_for_fixtures([fixture], min_edge=0.03)
    capped = service.build_board(league='epl', days=3, limit=1, min_edge=0.03)

    # build_board with limit=1 truncates; build_board_for_fixtures must not.
    assert len(full.candidates) >= len(capped.candidates)
    assert len(full.candidates) > 1


def test_evaluate_fixture_requests_season_window_snapshot() -> None:
    # Team strength must be estimated over a season-spanning window, not the
    # last 5 matches (5 matches is streak noise — see the calibration spec).
    from nutmeg.services.value import _STRENGTH_WINDOW_MATCHES

    fixture = _fixture('1379305')
    recorded: dict[str, int] = {}

    class _RecordingSnapshotService:
        def build_snapshot(self, fixture_id: str, *, recent_matches: int = 5):
            recorded['recent_matches'] = recent_matches
            return _snapshot(fixture)

    service = ValueBoardService(
        fixture_repository=None,  # type: ignore[arg-type]
        snapshot_service=_RecordingSnapshotService(),
        odds_service=FakeOddsService({fixture.fixture_id: _odds(fixture)}),
    )

    service.build_board_for_fixtures([fixture], min_edge=0.03)

    assert recorded['recent_matches'] == _STRENGTH_WINDOW_MATCHES
    assert _STRENGTH_WINDOW_MATCHES >= 34
