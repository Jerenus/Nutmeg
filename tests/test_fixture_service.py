from __future__ import annotations

from dataclasses import replace

from nutmeg.domain.fixtures import sample_fixtures
from nutmeg.services.fixtures import FixtureService


class FakeFixtureRepository:
    def __init__(self, fixtures):
        self.fixtures = fixtures

    def list_upcoming(self, league: str, days: int):
        return self.fixtures

    def upsert_many(self, fixtures):
        self.fixtures = fixtures
        return len(fixtures)


def test_fixture_service_excludes_demo_cache_when_real_fixtures_exist() -> None:
    demo_fixture, second_demo_fixture = sample_fixtures('epl')
    real_fixture = replace(
        second_demo_fixture,
        fixture_id='1379305',
        source='api-football',
        provider_league_id=39,
        home_team='Manchester United',
        away_team='Brentford',
    )
    service = FixtureService(FakeFixtureRepository([demo_fixture, real_fixture]))

    fixtures = service.list_upcoming('epl', 3)

    assert [fixture.fixture_id for fixture in fixtures] == ['1379305']
