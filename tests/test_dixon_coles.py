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

