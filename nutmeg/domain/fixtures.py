from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


