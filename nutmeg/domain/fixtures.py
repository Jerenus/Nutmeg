from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class FixtureStatus(StrEnum):
    SCHEDULED = 'scheduled'
    LIVE = 'live'
    FINISHED = 'finished'
    UNKNOWN = 'unknown'

    @classmethod
    def from_api_short(cls, short_code: str | None) -> 'FixtureStatus':
        if short_code in {'NS', 'TBD', 'PST', 'SUSP', 'INT'}:
            return cls.SCHEDULED
        if short_code in {'1H', '2H', 'HT', 'ET', 'BT', 'LIVE'}:
            return cls.LIVE
        if short_code in {'FT', 'AET', 'PEN'}:
            return cls.FINISHED
        return cls.UNKNOWN


@dataclass(slots=True, frozen=True)
class Fixture:
    fixture_id: str
    league_code: str
    provider_league_id: int
    season: int
    kickoff_at: datetime
    home_team_id: int | None
    away_team_id: int | None
    home_team: str
    away_team: str
    source: str = 'demo'
    status: FixtureStatus = FixtureStatus.SCHEDULED
    status_short: str = 'NS'
    status_long: str = 'Not Started'
    round_name: str | None = None
    venue: str | None = None
    referee: str | None = None
    home_goals: int | None = None
    away_goals: int | None = None
    penalty_home: int | None = None
    penalty_away: int | None = None


def sample_fixtures(league_code: str) -> list[Fixture]:
    now = datetime.now(UTC).replace(microsecond=0)
    season = now.year if now.month >= 7 else now.year - 1
    return [
        Fixture(
            fixture_id=f'{league_code}-001',
            league_code=league_code,
            provider_league_id=0,
            season=season,
            kickoff_at=now + timedelta(days=1, hours=3),
            home_team_id=42,
            away_team_id=148,
            home_team='Arsenal',
            away_team='Tottenham Hotspur',
            venue='Emirates Stadium',
        ),
        Fixture(
            fixture_id=f'{league_code}-002',
            league_code=league_code,
            provider_league_id=0,
            season=season,
            kickoff_at=now + timedelta(days=2, hours=1),
            home_team_id=50,
            away_team_id=40,
            home_team='Manchester City',
            away_team='Liverpool',
            venue='Etihad Stadium',
        ),
    ]
