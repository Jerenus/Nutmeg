from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.domain.fixtures import sample_fixtures
from nutmeg.domain.operations import TelegramDispatchStatus
from nutmeg.domain.value import ValueBoard, ValueCandidate
from nutmeg.services.operations import DailyOperatorService
from nutmeg.services.popularity import MatchPopularityRanker


@dataclass(slots=True, frozen=True)
class FakeSyncReport:
    total_fixtures: int
    total_requests: int


class FakeSyncService:
    def __init__(self) -> None:
        self.calls = []

    def sync(self, league_codes, days, timezone, past_days=0):
        self.calls.append(
            {
                'league_codes': league_codes,
                'days': days,
                'timezone': timezone,
                'past_days': past_days,
            }
        )
        return FakeSyncReport(total_fixtures=2, total_requests=1)


class FakeFixtureService:
    def list_upcoming(self, league: str, days: int, demo: bool = False):
        assert league == 'epl'
        assert days == 3
        assert demo is False
        return sample_fixtures('epl')


class FakeValueBoardService:
    def build_board(self, *, league: str, days: int, limit: int, min_edge: float):
        assert league == 'epl'
        assert days == 3
        assert limit == 5
        assert min_edge == 0.03
        fixture = sample_fixtures('epl')[0]
        return ValueBoard(
            league='epl',
            days=3,
            generated_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
            candidates=[
                ValueCandidate(
                    fixture_id=fixture.fixture_id,
                    kickoff_at=fixture.kickoff_at,
                    home_team=fixture.home_team,
                    away_team=fixture.away_team,
                    outcome_key='home',
                    outcome_name='Home',
                    model_probability=0.56,
                    market_probability=0.45,
                    edge=0.11,
                    best_odds=2.2,
                    expected_value=0.232,
                    quarter_kelly_fraction=0.048,
                    rating='strong',
                    model_name='dixon-coles-lite-poisson',
                    source_notes=['test'],
                )
            ],
            skipped=[],
        )


def test_daily_operator_service_orchestrates_sync_popularity_value_and_dry_run_dispatch() -> None:
    sync_service = FakeSyncService()
    service = DailyOperatorService(
        fixture_service=FakeFixtureService(),
        popularity_ranker=MatchPopularityRanker(),
        value_board_service=FakeValueBoardService(),
        sync_service=sync_service,
    )

    summary = service.run(
        league='epl',
        days=3,
        limit=5,
        query='Give me the pre-match operator brief.',
        dry_run=True,
        live_sync=True,
        briefs=False,
        dispatch_telegram=True,
    )

    assert sync_service.calls == [
        {'league_codes': ['epl'], 'days': 3, 'timezone': 'UTC', 'past_days': 0}
    ]
    assert summary.sync_status == 'succeeded'
    assert summary.sync_fixtures_written == 2
    assert summary.fixtures_considered == 2
    assert summary.popular_matches
    assert summary.value_candidates
    assert summary.telegram_dispatch.status == TelegramDispatchStatus.DRY_RUN
