from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.config.settings import get_settings
from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.odds import (
    MarketOddsSnapshot,
    OddsProviderSnapshot,
    OddsSnapshot,
    OutcomeOddsSnapshot,
)
from nutmeg.storage.bootstrap import create_analytics_schema
from nutmeg.storage.odds_repository import DuckDbOddsHistoryRepository


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


def _snapshot(captured_at: datetime, fair_probability: float) -> OddsSnapshot:
    return OddsSnapshot(
        fixture=_fixture(),
        provider=OddsProviderSnapshot(
            name='api-football',
            updated_at=captured_at,
            bookmaker_count=2,
        ),
        markets={
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
                        bookmaker_quotes=[],
                        fair_probability=fair_probability,
                        fair_odds=round(1 / fair_probability, 3),
                        best_odds=1.9,
                        bookmaker_count=2,
                    ),
                    OutcomeOddsSnapshot(
                        outcome_key='under',
                        outcome_name='Under',
                        bookmaker_quotes=[],
                        fair_probability=round(1 - fair_probability, 6),
                        fair_odds=round(1 / (1 - fair_probability), 3),
                        best_odds=1.95,
                        bookmaker_count=2,
                    ),
                ],
            )
        },
        deferred_sections=[],
    )


def test_duckdb_odds_history_repository_round_trips_market_points() -> None:
    settings = get_settings()
    create_analytics_schema(settings)
    repository = DuckDbOddsHistoryRepository(settings)

    repository.append_snapshot(_snapshot(datetime(2026, 4, 24, 6, 0, tzinfo=UTC), 0.54))
    repository.append_snapshot(_snapshot(datetime(2026, 4, 24, 7, 0, tzinfo=UTC), 0.57))

    points = repository.list_market_history('1234', market_key='totals_2_5', line='2.5')

    assert len(points) == 2
    assert points[0].outcome_probabilities['over'] == 0.54
    assert points[1].outcome_probabilities['over'] == 0.57
    assert points[1].outcome_best_odds['under'] == 1.95
