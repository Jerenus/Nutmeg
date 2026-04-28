from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from typing import Protocol

from nutmeg.config.team_catalog import TeamCatalog, load_team_catalog
from nutmeg.domain.players import (
    PlayerAvailability,
    PlayerIdentityProfile,
    PlayerMarketProfile,
    PlayerProfile,
    PlayerProfileUnavailable,
    PlayerSeasonMetrics,
    SimilarPlayer,
)
from nutmeg.storage.duckdb_utils import connect_analytics_db
from nutmeg.storage.reference_repository import normalize_person_name


class PlayerReferenceRepository(Protocol):
    def resolve_player_identity(
        self,
        *,
        league_code: str,
        team_name: str,
        provider: str,
        player_name: str,
        position: str | None = None,
        provider_player_id: str | None = None,
    ):
        ...


@dataclass(slots=True, frozen=True)
class _PlayerMetricRow:
    league: str
    season: int
    team_name: str
    player_name: str
    position: str | None
    metrics: PlayerSeasonMetrics


class PlayerProfileService:
    def __init__(
        self,
        *,
        database_path: Path,
        reference_repository: PlayerReferenceRepository,
        team_catalog: TeamCatalog | None = None,
    ) -> None:
        self._database_path = database_path
        self._reference_repository = reference_repository
        self._team_catalog = team_catalog or load_team_catalog()

    def build_profile(
        self,
        *,
        league: str,
        season: int | None,
        team: str,
        player: str,
        similar_limit: int = 5,
    ) -> PlayerProfile:
        resolved_team = self._team_catalog.normalize(team)
        resolved_identity = self._reference_repository.resolve_player_identity(
            league_code=league,
            team_name=resolved_team,
            provider='player-profile',
            player_name=player,
        )
        canonical_player = (
            resolved_identity.canonical_name if resolved_identity is not None else player
        )
        resolved_season = season or _default_season()
        identity = (
            PlayerIdentityProfile(
                identity_id=resolved_identity.identity_id,
                canonical_name=resolved_identity.canonical_name,
                team_name=resolved_team,
                match_confidence=resolved_identity.match_confidence,
            )
            if resolved_identity is not None
            else None
        )

        market = self._fetch_market_profile(
            league=league,
            team=resolved_team,
            player=canonical_player,
        )
        season_metrics = self._fetch_season_metrics(
            league=league,
            season=resolved_season,
            team=resolved_team,
            player=canonical_player,
        )
        availability = self._fetch_availability(
            league=league,
            team=resolved_team,
            player=canonical_player,
        )
        similar_players = (
            self._similar_players(
                league=league,
                season=resolved_season,
                target_team=resolved_team,
                target_player=canonical_player,
                target_metrics=season_metrics,
                limit=similar_limit,
            )
            if season_metrics is not None
            else []
        )

        unavailable = []
        if identity is None:
            unavailable.append(PlayerProfileUnavailable.IDENTITY.value)
        if market is None:
            unavailable.append(PlayerProfileUnavailable.MARKET.value)
        if season_metrics is None:
            unavailable.append(PlayerProfileUnavailable.SEASON_METRICS.value)
        if availability is None:
            unavailable.append(PlayerProfileUnavailable.AVAILABILITY.value)
        if not similar_players:
            unavailable.append(PlayerProfileUnavailable.SIMILAR_PLAYERS.value)

        return PlayerProfile(
            query_player=player,
            query_team=team,
            league=league,
            season=resolved_season,
            generated_at=datetime.now(UTC).replace(microsecond=0),
            identity=identity,
            market=market,
            season_metrics=season_metrics,
            availability=availability,
            similar_players=similar_players,
            unavailable_sections=unavailable,
        )

    def _fetch_market_profile(
        self,
        *,
        league: str,
        team: str,
        player: str,
    ) -> PlayerMarketProfile | None:
        with connect_analytics_db(self._database_path) as connection:
            if not self._table_exists(connection, 'tm_clubs_cache') or not self._table_exists(
                connection,
                'tm_players_cache',
            ):
                return None
            club_id = self._club_id(connection, league=league, team=team)
            if club_id is None:
                return None
            rows = connection.execute(
                '''
                SELECT player_id, name, position, market_value_in_eur
                FROM tm_players_cache
                WHERE current_club_id = ?
                ''',
                [club_id],
            ).fetchall()
        normalized_target = normalize_person_name(player)
        for player_id, name, position, market_value in rows:
            if normalize_person_name(str(name)) != normalized_target:
                continue
            return PlayerMarketProfile(
                provider_player_id=str(player_id) if player_id is not None else None,
                position=position,
                market_value_eur=int(market_value) if market_value is not None else None,
                source='transfermarkt-datasets',
            )
        return None

    def _fetch_season_metrics(
        self,
        *,
        league: str,
        season: int,
        team: str,
        player: str,
    ) -> PlayerSeasonMetrics | None:
        row = self._metric_row(
            league=league,
            season=season,
            team=team,
            player=player,
        )
        return row.metrics if row is not None else None

    def _fetch_availability(
        self,
        *,
        league: str,
        team: str,
        player: str,
    ) -> PlayerAvailability | None:
        with connect_analytics_db(self._database_path) as connection:
            if not self._table_exists(connection, 'player_availability_cache'):
                return None
            rows = connection.execute(
                '''
                SELECT player_name, status, reason, expected_return, source
                FROM player_availability_cache
                WHERE league_code = ? AND team_name = ?
                ''',
                [league, team],
            ).fetchall()
        normalized_target = normalize_person_name(player)
        for name, status, reason, expected_return, source in rows:
            if normalize_person_name(str(name)) != normalized_target:
                continue
            return PlayerAvailability(
                status=status,
                reason=reason,
                expected_return=expected_return,
                source=source,
            )
        return None

    def _similar_players(
        self,
        *,
        league: str,
        season: int,
        target_team: str,
        target_player: str,
        target_metrics: PlayerSeasonMetrics,
        limit: int,
    ) -> list[SimilarPlayer]:
        rows = self._all_metric_rows(league=league, season=season)
        target_normalized = normalize_person_name(target_player)
        candidates: list[SimilarPlayer] = []
        for row in rows:
            if (
                row.team_name == target_team
                and normalize_person_name(row.player_name) == target_normalized
            ):
                continue
            score = _cosine_similarity(target_metrics.vector(), row.metrics.vector())
            candidates.append(
                SimilarPlayer(
                    player_name=row.player_name,
                    team_name=row.team_name,
                    position=row.position,
                    similarity_score=round(score, 6),
                    source=row.metrics.source,
                )
            )
        return sorted(
            candidates,
            key=lambda item: (-item.similarity_score, item.team_name, item.player_name),
        )[:limit]

    def _metric_row(
        self,
        *,
        league: str,
        season: int,
        team: str,
        player: str,
    ) -> _PlayerMetricRow | None:
        normalized_target = normalize_person_name(player)
        for row in self._all_metric_rows(league=league, season=season):
            if row.team_name != team:
                continue
            if normalize_person_name(row.player_name) == normalized_target:
                return row
        return None

    def _all_metric_rows(self, *, league: str, season: int) -> list[_PlayerMetricRow]:
        with connect_analytics_db(self._database_path) as connection:
            if not self._table_exists(connection, 'sd_player_season_cache'):
                return []
            rows = connection.execute(
                '''
                SELECT
                    league_code,
                    season,
                    team_name,
                    player_name,
                    position,
                    minutes,
                    goals_per90,
                    assists_per90,
                    xg_per90,
                    xa_per90,
                    key_passes_per90,
                    duels_won_per90
                FROM sd_player_season_cache
                WHERE league_code = ? AND season = ?
                ''',
                [league, season],
            ).fetchall()
        return [
            _PlayerMetricRow(
                league=row[0],
                season=int(row[1]),
                team_name=row[2],
                player_name=row[3],
                position=row[4],
                metrics=PlayerSeasonMetrics(
                    source='soccerdata-cache',
                    minutes=float(row[5]) if row[5] is not None else None,
                    goals_per90=_float_or_none(row[6]),
                    assists_per90=_float_or_none(row[7]),
                    xg_per90=_float_or_none(row[8]),
                    xa_per90=_float_or_none(row[9]),
                    key_passes_per90=_float_or_none(row[10]),
                    duels_won_per90=_float_or_none(row[11]),
                ),
            )
            for row in rows
        ]

    def _club_id(self, connection, *, league: str, team: str) -> int | None:
        from nutmeg.config.catalog import get_league

        league_config = get_league(league)
        source_team = self._team_catalog.resolve_source_name(team, 'transfermarkt')
        row = connection.execute(
            '''
            SELECT club_id
            FROM tm_clubs_cache
            WHERE name = ?
              AND (? IS NULL OR domestic_competition_id = ?)
            LIMIT 1
            ''',
            [
                source_team,
                league_config.transfermarkt_competition_id,
                league_config.transfermarkt_competition_id,
            ],
        ).fetchone()
        return int(row[0]) if row is not None else None

    def _table_exists(self, connection, table_name: str) -> bool:
        return bool(
            connection.execute(
                '''
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_name = ?
                ''',
                [table_name],
            ).fetchone()[0]
        )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _float_or_none(value) -> float | None:
    return float(value) if value is not None else None


def _default_season() -> int:
    now = datetime.now(UTC)
    return now.year if now.month >= 7 else now.year - 1
