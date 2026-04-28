from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PlayerProfileUnavailable(StrEnum):
    IDENTITY = 'identity'
    MARKET = 'market'
    SEASON_METRICS = 'season_metrics'
    AVAILABILITY = 'availability'
    SIMILAR_PLAYERS = 'similar_players'


@dataclass(slots=True, frozen=True)
class PlayerIdentityProfile:
    identity_id: str
    canonical_name: str
    team_name: str
    match_confidence: str


@dataclass(slots=True, frozen=True)
class PlayerMarketProfile:
    provider_player_id: str | None
    position: str | None
    market_value_eur: int | None
    source: str


@dataclass(slots=True, frozen=True)
class PlayerSeasonMetrics:
    source: str
    minutes: float | None
    goals_per90: float | None
    assists_per90: float | None
    xg_per90: float | None
    xa_per90: float | None
    key_passes_per90: float | None
    duels_won_per90: float | None

    def vector(self) -> list[float]:
        return [
            float(value or 0.0)
            for value in (
                self.goals_per90,
                self.assists_per90,
                self.xg_per90,
                self.xa_per90,
                self.key_passes_per90,
                self.duels_won_per90,
            )
        ]


@dataclass(slots=True, frozen=True)
class PlayerAvailability:
    status: str
    reason: str | None
    expected_return: str | None
    source: str


@dataclass(slots=True, frozen=True)
class SimilarPlayer:
    player_name: str
    team_name: str
    position: str | None
    similarity_score: float
    source: str


@dataclass(slots=True, frozen=True)
class PlayerProfile:
    query_player: str
    query_team: str
    league: str
    season: int
    generated_at: datetime
    identity: PlayerIdentityProfile | None
    market: PlayerMarketProfile | None
    season_metrics: PlayerSeasonMetrics | None
    availability: PlayerAvailability | None
    similar_players: list[SimilarPlayer]
    unavailable_sections: list[str] = field(default_factory=list)

