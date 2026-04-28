from __future__ import annotations

from nutmeg.core.repositories import FixtureRepository
from nutmeg.domain.fixtures import Fixture, sample_fixtures


class FixtureService:
    def __init__(self, repository: FixtureRepository) -> None:
        self._repository = repository

    def list_upcoming(
        self,
        league: str,
        days: int,
        demo: bool = False,
    ) -> list[Fixture]:
        if demo:
            return sample_fixtures(league)
        fixtures = self._repository.list_upcoming(league=league, days=days)
        real_fixtures = [fixture for fixture in fixtures if fixture.source != 'demo']
        return real_fixtures or fixtures

    def seed_demo(self, league: str) -> list[Fixture]:
        fixtures = sample_fixtures(league)
        self._repository.upsert_many(fixtures=fixtures)
        return fixtures
