from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nutmeg.domain.fixtures import Fixture


@dataclass(slots=True, frozen=True)
class TeamSeasonMetrics:
    matches: float | None
    goals: float | None
    shots: float | None
    shots_on_target: float | None
    xg: float | None
    non_penalty_xg: float | None


@dataclass(slots=True, frozen=True)
class TeamRecentForm:
    matches: int
    wins: int
    draws: int
    losses: int
    points: int
    expected_points: float
    goals_for: float
    goals_against: float
    xg_for: float
    xg_against: float


@dataclass(slots=True, frozen=True)
class TeamShotSummary:
    shots: int
    goals: int
    total_xg: float
    open_play_shots: int


@dataclass(slots=True, frozen=True)
class TeamMarketValue:
    source: str
    total_market_value_eur: int | None
    top_players: list[tuple[str, int]]


@dataclass(slots=True, frozen=True)
class VenueReference:
    venue_key: str
    venue_name: str
    country_name: str | None
    latitude: float
    longitude: float
    timezone: str | None
    source: str


@dataclass(slots=True, frozen=True)
class WeatherContext:
    forecast_at: datetime
    temperature_c: float | None
    precipitation_probability: int | None
    wind_speed_kph: float | None
    weather_code: int | None
    source: str


@dataclass(slots=True, frozen=True)
class AvailabilityRecord:
    player_name: str
    status: str
    reason: str | None
    expected_return: str | None
    source: str


@dataclass(slots=True, frozen=True)
class InjuryStatus:
    player_name: str
    status: str
    reason: str | None
    expected_return: str | None
    source: str


@dataclass(slots=True, frozen=True)
class LineupPlayer:
    player_name: str
    position: str | None
    shirt_number: str | None
    role: str
    captain: bool


@dataclass(slots=True, frozen=True)
class TeamLineup:
    status: str
    source: str
    formation: str | None
    players: list[LineupPlayer]


@dataclass(slots=True, frozen=True)
class BenchDepthContext:
    bench_market_value_eur: int | None
    available_players: int
    label: str
    source: str


@dataclass(slots=True, frozen=True)
class AvailabilityContext:
    injuries: list[AvailabilityRecord]
    suspensions: list[AvailabilityRecord]
    returning_players: list[AvailabilityRecord]
    expected_absences_summary: str | None
    bench_depth: BenchDepthContext | None


@dataclass(slots=True, frozen=True)
class TravelContext:
    distance_km: float | None
    bucket: str | None
    source: str


@dataclass(slots=True, frozen=True)
class EnvironmentContext:
    venue_name: str | None
    referee: str | None
    kickoff_local_time: datetime | None
    weather: WeatherContext | None
    home_rest_days: int | None
    away_rest_days: int | None
    away_travel: TravelContext | None
    source_names: dict[str, str]


@dataclass(slots=True, frozen=True)
class HeadToHeadSummary:
    matches: int
    home_wins: int
    draws: int
    away_wins: int
    source: str


@dataclass(slots=True, frozen=True)
class TeamSplitSummary:
    home_points_per_match: float | None
    away_points_per_match: float | None
    home_goals_for_per_match: float | None
    away_goals_for_per_match: float | None
    source: str


@dataclass(slots=True, frozen=True)
class TeamTrendSummary:
    sample_size: int
    goals_for_per_match: float | None
    xg_for_per_match: float | None
    goals_against_per_match: float | None
    xg_against_per_match: float | None
    set_piece_shot_share: float | None
    source: str


@dataclass(slots=True, frozen=True)
class MatchupTrendContext:
    head_to_head: HeadToHeadSummary | None
    home_split: TeamSplitSummary | None
    away_split: TeamSplitSummary | None
    home_trend: TeamTrendSummary | None
    away_trend: TeamTrendSummary | None


@dataclass(slots=True, frozen=True)
class TeamEnrichment:
    canonical_name: str
    source_names: dict[str, str]
    season_metrics: TeamSeasonMetrics | None
    recent_form: TeamRecentForm | None
    shot_summary: TeamShotSummary | None
    market_value: TeamMarketValue | None
    injuries: list[InjuryStatus]
    lineup: TeamLineup | None
    availability: AvailabilityContext | None = None


@dataclass(slots=True, frozen=True)
class SoccerDataFixtureBundle:
    league_code: str
    season: int
    home: TeamEnrichment
    away: TeamEnrichment


@dataclass(slots=True, frozen=True)
class FixtureSnapshot:
    fixture: Fixture
    home: TeamEnrichment
    away: TeamEnrichment
    deferred_sections: list[str]
    generated_at: datetime
    environment: EnvironmentContext | None = None
    matchup: MatchupTrendContext | None = None


def snapshot_timestamp() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
