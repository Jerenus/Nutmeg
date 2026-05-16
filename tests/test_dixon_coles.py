from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.snapshot import (
    FixtureSnapshot,
    MatchupTrendContext,
    TeamEnrichment,
    TeamTrendSummary,
)
from nutmeg.models.dixon_coles import (
    DixonColesLiteModel,
    ExpectedGoals,
    expected_goals_from_snapshot,
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


def _snapshot() -> FixtureSnapshot:
    fixture = Fixture(
        fixture_id='fx-1',
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
    return FixtureSnapshot(
        fixture=fixture,
        home=_team('Arsenal'),
        away=_team('Tottenham Hotspur'),
        deferred_sections=[],
        generated_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        matchup=MatchupTrendContext(
            head_to_head=None,
            home_split=None,
            away_split=None,
            home_trend=TeamTrendSummary(
                sample_size=5,
                goals_for_per_match=2.1,
                xg_for_per_match=2.0,
                goals_against_per_match=0.9,
                xg_against_per_match=0.8,
                set_piece_shot_share=None,
                source='test',
            ),
            away_trend=TeamTrendSummary(
                sample_size=5,
                goals_for_per_match=1.1,
                xg_for_per_match=1.0,
                goals_against_per_match=1.9,
                xg_against_per_match=1.8,
                set_piece_shot_share=None,
                source='test',
            ),
        ),
    )


def test_dixon_coles_lite_probabilities_sum_to_one_and_favor_stronger_side() -> None:
    probabilities = DixonColesLiteModel(max_goals=9).price(ExpectedGoals(home=2.0, away=0.8))

    assert round(sum(probabilities.as_dict().values()), 6) == 1.0
    assert probabilities.home_win > probabilities.away_win
    assert probabilities.home_win > probabilities.draw
    assert probabilities.model_name == 'dixon-coles-lite-poisson'


def test_expected_goals_from_snapshot_uses_recent_xg_matchup() -> None:
    expected_goals = expected_goals_from_snapshot(_snapshot())

    assert expected_goals.home == 1.9
    assert expected_goals.away == 0.9
    assert expected_goals.source == 'recent-xg-matchup'


def test_price_markets_total_goals_buckets_sum_to_one() -> None:
    markets = DixonColesLiteModel(max_goals=9).price_markets(
        ExpectedGoals(home=1.6, away=1.2)
    )

    total_goals = markets.total_goals
    expected_keys = {
        'total_0',
        'total_1',
        'total_2',
        'total_3',
        'total_4',
        'total_5',
        'total_6',
        'total_7_plus',
    }
    assert set(total_goals) == expected_keys
    assert round(sum(total_goals.values()), 6) == 1.0
    assert all(0.0 <= probability <= 1.0 for probability in total_goals.values())


def test_price_markets_total_goals_seven_plus_is_residual_tail() -> None:
    markets = DixonColesLiteModel(max_goals=9).price_markets(
        ExpectedGoals(home=3.5, away=3.5)
    )

    # A high-scoring matchup keeps meaningful mass in the 7+ tail bucket.
    assert markets.total_goals['total_7_plus'] > 0.05


def test_price_markets_correct_score_grid_sums_to_one_and_favours_strong_side() -> None:
    markets = DixonColesLiteModel(max_goals=9).price_markets(
        ExpectedGoals(home=2.0, away=0.7)
    )

    correct_score = markets.correct_score
    assert round(sum(correct_score.values()), 6) == 1.0
    # A dominant home side should make a 1-0 more likely than a 0-1.
    assert correct_score['score_1_0'] > correct_score['score_0_1']
    # Every key follows the score_<home>_<away> convention.
    assert all(key.startswith('score_') for key in correct_score)


def test_price_markets_handicap_lines_sum_to_one_per_line() -> None:
    markets = DixonColesLiteModel(max_goals=9).price_markets(
        ExpectedGoals(home=1.8, away=1.0)
    )

    handicap = markets.handicap
    # Integer handicap lines applied to the home side.
    assert 'handicap_home_minus_1' in handicap
    assert 'handicap_home_plus_1' in handicap
    for line_outcomes in handicap.values():
        assert set(line_outcomes) == {'home', 'draw', 'away'}
        assert round(sum(line_outcomes.values()), 6) == 1.0


def test_price_markets_handicap_minus_one_is_harder_than_scratch() -> None:
    markets = DixonColesLiteModel(max_goals=9).price_markets(
        ExpectedGoals(home=1.8, away=1.0)
    )

    # Giving the home side a -1 line lowers its win probability vs the level line.
    scratch_home = markets.handicap['handicap_home_0']['home']
    minus_one_home = markets.handicap['handicap_home_minus_1']['home']
    assert minus_one_home < scratch_home


def test_price_markets_match_winner_matches_legacy_price() -> None:
    expected_goals = ExpectedGoals(home=2.0, away=0.8)
    model = DixonColesLiteModel(max_goals=9)

    legacy = model.price(expected_goals)
    markets = model.price_markets(expected_goals)

    assert markets.match_winner == legacy.as_dict()
    assert markets.model_name == legacy.model_name
    assert markets.expected_goals_source == expected_goals.source

