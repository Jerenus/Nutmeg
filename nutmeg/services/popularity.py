from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture, FixtureStatus


@dataclass(slots=True, frozen=True)
class MatchPopularityScore:
    score: int
    tier: str
    reasons: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class RankedFixture:
    rank: int
    fixture: Fixture
    popularity: MatchPopularityScore


class MatchPopularityRanker:
    _competition_weights = {
        'ucl': 55,
        'uel': 42,
        'epl': 40,
        'laliga': 36,
        'seriea': 32,
        'bundesliga': 32,
        'ligue1': 28,
        'facup': 24,
        'efl_cup': 18,
    }
    _team_weights = {
        'arsenal': 30,
        'aston villa': 16,
        'athletic club': 16,
        'atletico madrid': 28,
        'barcelona': 38,
        'bayern munich': 38,
        'borussia dortmund': 28,
        'brentford': 10,
        'brighton': 14,
        'chelsea': 30,
        'everton': 16,
        'fulham': 8,
        'inter milan': 32,
        'juventus': 30,
        'liverpool': 36,
        'manchester city': 36,
        'manchester united': 34,
        'newcastle united': 20,
        'paris saint-germain': 34,
        'real madrid': 40,
        'roma': 24,
        'tottenham': 26,
        'tottenham hotspur': 26,
        'west ham': 14,
        'west ham united': 14,
    }
    _rivalry_bonuses: dict[frozenset[str], tuple[int, str]] = {
        frozenset({'arsenal', 'tottenham hotspur'}): (20, 'North London derby'),
        frozenset({'barcelona', 'real madrid'}): (28, 'El Clasico rivalry'),
        frozenset({'inter milan', 'juventus'}): (18, 'Italian title rivalry'),
        frozenset({'liverpool', 'manchester city'}): (18, 'modern title rivalry'),
        frozenset({'liverpool', 'manchester united'}): (24, 'historic English rivalry'),
        frozenset({'manchester city', 'manchester united'}): (24, 'Manchester derby'),
    }

    def rank(
        self,
        fixtures: list[Fixture],
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[RankedFixture]:
        reference_time = now or datetime.now(UTC)
        scored = [
            (fixture, self.score_fixture(fixture, now=reference_time))
            for fixture in fixtures
        ]
        scored.sort(
            key=lambda item: (
                -item[1].score,
                item[0].kickoff_at,
                item[0].fixture_id,
            )
        )
        if limit is not None:
            scored = scored[:limit]
        return [
            RankedFixture(rank=index + 1, fixture=fixture, popularity=popularity)
            for index, (fixture, popularity) in enumerate(scored)
        ]

    def score_fixture(
        self,
        fixture: Fixture,
        *,
        now: datetime | None = None,
    ) -> MatchPopularityScore:
        reference_time = now or datetime.now(UTC)
        score = 0
        reasons: list[str] = []

        competition_score = self._competition_weights.get(fixture.league_code.casefold(), 12)
        score += competition_score
        reasons.append(f'{fixture.league_code.upper()} competition weight +{competition_score}')

        home_key = self._team_key(fixture.home_team)
        away_key = self._team_key(fixture.away_team)
        home_weight = self._team_weights.get(home_key, 0)
        away_weight = self._team_weights.get(away_key, 0)
        team_score = home_weight + away_weight
        if team_score:
            score += team_score
            reasons.append(
                f'major teams {fixture.home_team} +{home_weight}, '
                f'{fixture.away_team} +{away_weight}'
            )

        if min(home_weight, away_weight) >= 26:
            score += 16
            reasons.append('elite matchup +16')

        rivalry = self._rivalry_bonuses.get(frozenset({home_key, away_key}))
        if rivalry is not None:
            bonus, label = rivalry
            score += bonus
            reasons.append(f'{label} +{bonus}')

        timing_score, timing_reason = self._timing_score(fixture, reference_time)
        score += timing_score
        reasons.append(timing_reason)

        return MatchPopularityScore(
            score=score,
            tier=self._tier(score),
            reasons=tuple(reasons),
        )

    def _timing_score(self, fixture: Fixture, now: datetime) -> tuple[int, str]:
        if fixture.status == FixtureStatus.LIVE:
            return 24, 'live now +24'
        delta_hours = (fixture.kickoff_at - now).total_seconds() / 3600
        if delta_hours < 0:
            return 2, 'recently started or stale status +2'
        if delta_hours <= 24:
            return 12, 'kicks off within 24h +12'
        if delta_hours <= 72:
            return 6, 'kicks off within 72h +6'
        if delta_hours <= 168:
            return 2, 'kicks off this week +2'
        return 0, 'outside immediate window +0'

    def _tier(self, score: int) -> str:
        if score >= 105:
            return 'headline'
        if score >= 80:
            return 'strong'
        if score >= 55:
            return 'watchlist'
        return 'normal'

    def _team_key(self, value: str) -> str:
        return ' '.join(value.casefold().replace('&', 'and').split())
