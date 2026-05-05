"""Baseline + popularity adapters for the JCZQ analytics layer.

Wraps the shared `MatchPopularityRanker` and exposes a small adapter that
converts raw `JczqDailyMatch` rows into the popularity (score, tier) tuple the
analytics consumer expects. Also re-exports `LeaguePriorBaseline` so callers
can construct the full provider stack from one module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nutmeg.domain.fixtures import Fixture, FixtureStatus
from nutmeg.domain.jczq_daily import JczqDailyMatch
from nutmeg.services.jczq_intelligence import LeaguePriorBaseline
from nutmeg.services.popularity import MatchPopularityRanker

__all__ = [
    "JczqPopularityAdapter",
    "LeaguePriorBaseline",
    "build_default_providers",
]

_LEAGUE_TO_CODE = {
    "英超": "epl",
    "西甲": "laliga",
    "意甲": "seriea",
    "德甲": "bundesliga",
    "法甲": "ligue1",
    "欧冠": "ucl",
    "欧联": "uel",
    "英足总": "facup",
    "英联杯": "efl_cup",
}


@dataclass(slots=True)
class JczqPopularityAdapter:
    ranker: MatchPopularityRanker
    now: datetime | None = None

    def get(self, match: JczqDailyMatch) -> tuple[int, str]:
        fixture = _to_fixture(match)
        score = self.ranker.score_fixture(fixture, now=self.now or datetime.now(UTC))
        return score.score, score.tier


def build_default_providers(
    *,
    overrides: dict[str, tuple[float, float, float]] | None = None,
    now: datetime | None = None,
) -> tuple[LeaguePriorBaseline, JczqPopularityAdapter]:
    return (
        LeaguePriorBaseline(overrides=overrides or {}),
        JczqPopularityAdapter(ranker=MatchPopularityRanker(), now=now),
    )


def _to_fixture(match: JczqDailyMatch) -> Fixture:
    league_code = _LEAGUE_TO_CODE.get(match.league, match.league.lower() or "unknown")
    kickoff = _parse_kickoff(match.match_date, match.match_time)
    season = kickoff.year if kickoff.month >= 7 else kickoff.year - 1
    return Fixture(
        fixture_id=match.match_no or f"unknown-{match.home_team}-{match.away_team}",
        league_code=league_code,
        provider_league_id=0,
        season=season,
        kickoff_at=kickoff,
        home_team_id=None,
        away_team_id=None,
        home_team=match.home_team,
        away_team=match.away_team,
        source="jczq",
        status=FixtureStatus.SCHEDULED,
    )


def _parse_kickoff(match_date: str, match_time: str) -> datetime:
    if not match_date:
        return datetime.now(UTC) + timedelta(days=1)
    try:
        if match_time:
            return datetime.fromisoformat(f"{match_date}T{match_time}").replace(tzinfo=UTC)
        return datetime.fromisoformat(match_date).replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC) + timedelta(days=1)
