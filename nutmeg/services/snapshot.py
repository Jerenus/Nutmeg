from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nutmeg.config.catalog import get_league
from nutmeg.core.repositories import FixtureRepository
from nutmeg.data.api_football import ApiFootballClient, ApiFootballError
from nutmeg.data.open_meteo import OpenMeteoClient
from nutmeg.data.soccerdata_client import SoccerDataClient
from nutmeg.data.transfermarkt import TransfermarktDataset
from nutmeg.domain.snapshot import (
    AvailabilityContext,
    AvailabilityRecord,
    EnvironmentContext,
    FixtureSnapshot,
    MatchupTrendContext,
    TeamEnrichment,
    TeamLineup,
    TeamTrendSummary,
    snapshot_timestamp,
)
from nutmeg.storage.reference_repository import DuckDbReferenceRepository

_LOGGER = logging.getLogger(__name__)


class FixtureNotFoundError(LookupError):
    pass


class FixtureSnapshotService:
    def __init__(
        self,
        *,
        fixture_repository: FixtureRepository,
        soccerdata_client: SoccerDataClient,
        transfermarkt_dataset: TransfermarktDataset,
        api_context_client: ApiFootballClient,
        reference_repository: DuckDbReferenceRepository,
        weather_client: OpenMeteoClient,
    ) -> None:
        self._fixture_repository = fixture_repository
        self._soccerdata_client = soccerdata_client
        self._transfermarkt_dataset = transfermarkt_dataset
        self._api_context_client = api_context_client
        self._reference_repository = reference_repository
        self._weather_client = weather_client

    def build_snapshot(
        self,
        fixture_id: str,
        *,
        recent_matches: int = 5,
        live_context: bool = True,
    ) -> FixtureSnapshot:
        fixture = self._fixture_repository.get_fixture(fixture_id)
        if fixture is None:
            raise FixtureNotFoundError(f'Fixture `{fixture_id}` was not found in the local cache.')

        enrichment = self._soccerdata_client.fetch_fixture_enrichment(
            fixture=fixture,
            recent_matches=recent_matches,
        )
        if live_context:
            # API-Football enrichment degrades to empty when the provider is
            # unavailable (e.g. exhausted daily quota); soccerdata-sourced data
            # below is unaffected so the model side can still price the fixture.
            try:
                injuries_by_team = self._api_context_client.fetch_fixture_injuries(
                    fixture.fixture_id
                )
                confirmed_lineups = self._api_context_client.fetch_fixture_lineups(
                    fixture.fixture_id
                )
            except ApiFootballError as exc:
                _LOGGER.warning(
                    'API-Football unavailable for fixture %s; degrading to '
                    'soccerdata-only enrichment (no injuries/lineups): %s',
                    fixture.fixture_id,
                    exc,
                )
                injuries_by_team = {}
                confirmed_lineups = {}
            weather = self._weather_client.get_fixture_weather(fixture)
        else:
            injuries_by_team = {}
            confirmed_lineups = {}
            weather = None

        home_injuries = injuries_by_team.get(fixture.home_team_id or -1, [])
        away_injuries = injuries_by_team.get(fixture.away_team_id or -1, [])
        if live_context:
            home_sidelined = self._fetch_team_sidelined(
                fixture.home_team_id,
                fixture.season,
                as_of_date=fixture.kickoff_at.date(),
            )
            away_sidelined = self._fetch_team_sidelined(
                fixture.away_team_id,
                fixture.season,
                as_of_date=fixture.kickoff_at.date(),
            )
        else:
            home_sidelined = []
            away_sidelined = []
        home_market_value = self._transfermarkt_dataset.fetch_team_market_value(
            fixture.league_code,
            fixture.home_team,
        )
        away_market_value = self._transfermarkt_dataset.fetch_team_market_value(
            fixture.league_code,
            fixture.away_team,
        )

        home_lineup = confirmed_lineups.get(fixture.home_team_id or -1)
        away_lineup = confirmed_lineups.get(fixture.away_team_id or -1)
        if home_lineup is None:
            home_lineup = self._transfermarkt_dataset.build_probable_lineup(
                league_code=fixture.league_code,
                team_name=fixture.home_team,
                unavailable_players={injury.player_name for injury in home_injuries},
                recent_games=recent_matches,
            )
        if away_lineup is None:
            away_lineup = self._transfermarkt_dataset.build_probable_lineup(
                league_code=fixture.league_code,
                team_name=fixture.away_team,
                unavailable_players={injury.player_name for injury in away_injuries},
                recent_games=recent_matches,
            )
        home_lineup = self._filter_probable_lineup(
            fixture=fixture,
            team_name=fixture.home_team,
            lineup=home_lineup,
            injuries=home_injuries,
        )
        away_lineup = self._filter_probable_lineup(
            fixture=fixture,
            team_name=fixture.away_team,
            lineup=away_lineup,
            injuries=away_injuries,
        )

        home_availability = self._build_availability_context(
            fixture=fixture,
            team_name=fixture.home_team,
            injuries=home_injuries,
            sidelined=home_sidelined,
            lineup=home_lineup,
        )
        away_availability = self._build_availability_context(
            fixture=fixture,
            team_name=fixture.away_team,
            injuries=away_injuries,
            sidelined=away_sidelined,
            lineup=away_lineup,
        )

        home = self._with_snapshot_context(
            enrichment.home,
            market_value=home_market_value,
            injuries=home_injuries,
            lineup=home_lineup,
            availability=home_availability,
        )
        away = self._with_snapshot_context(
            enrichment.away,
            market_value=away_market_value,
            injuries=away_injuries,
            lineup=away_lineup,
            availability=away_availability,
        )

        return FixtureSnapshot(
            fixture=fixture,
            home=home,
            away=away,
            deferred_sections=[],
            generated_at=snapshot_timestamp(),
            environment=self._build_environment_context(
                fixture=fixture,
                weather=weather,
                include_travel=live_context,
            ),
            matchup=self._build_matchup_context(
                fixture=fixture,
                home=home,
                away=away,
                live_context=live_context,
            ),
        )

    def _filter_probable_lineup(
        self,
        *,
        fixture,
        team_name: str,
        lineup: TeamLineup | None,
        injuries,
    ) -> TeamLineup | None:
        if lineup is None or lineup.status != 'probable':
            return lineup

        unavailable_identity_ids = {
            resolved.identity_id
            for injury in injuries
            if (
                resolved := self._reference_repository.resolve_player_identity(
                    league_code=fixture.league_code,
                    team_name=team_name,
                    provider=injury.source,
                    player_name=injury.player_name,
                )
            )
        }
        unavailable_names = {injury.player_name for injury in injuries}
        filtered_players = []
        for player in lineup.players:
            resolved = self._reference_repository.resolve_player_identity(
                league_code=fixture.league_code,
                team_name=team_name,
                provider=lineup.source,
                player_name=player.player_name,
                position=player.position,
            )
            if resolved is not None and resolved.identity_id in unavailable_identity_ids:
                continue
            if player.player_name in unavailable_names:
                continue
            filtered_players.append(player)

        return TeamLineup(
            status=lineup.status,
            source=lineup.source,
            formation=lineup.formation,
            players=filtered_players,
        )

    def _with_snapshot_context(
        self,
        team: TeamEnrichment,
        *,
        market_value,
        injuries,
        lineup,
        availability: AvailabilityContext | None,
    ) -> TeamEnrichment:
        return replace(
            team,
            market_value=market_value,
            injuries=injuries,
            lineup=lineup,
            availability=availability,
        )

    def _fetch_team_sidelined(
        self,
        team_id: int | None,
        season: int,
        *,
        as_of_date: date | None = None,
    ) -> list[AvailabilityRecord]:
        if team_id is None:
            return []
        fetcher = getattr(self._api_context_client, 'fetch_team_sidelined', None)
        if not callable(fetcher):
            return []
        try:
            records = fetcher(
                team_id,
                season,
                as_of_date=as_of_date,
            )
        except ApiFootballError as exc:
            _LOGGER.warning(
                'API-Football unavailable for team %s sidelined records; '
                'degrading to empty: %s',
                team_id,
                exc,
            )
            return []
        return list(records or [])

    def _build_availability_context(
        self,
        *,
        fixture,
        team_name: str,
        injuries,
        sidelined: list[AvailabilityRecord],
        lineup: TeamLineup | None,
    ) -> AvailabilityContext:
        injury_records = [
            AvailabilityRecord(
                player_name=injury.player_name,
                status=injury.status,
                reason=injury.reason,
                expected_return=injury.expected_return,
                source=injury.source,
            )
            for injury in injuries
        ]
        suspensions = [
            record
            for record in sidelined
            if 'suspend' in record.status.lower()
        ]
        returning_players = [
            AvailabilityRecord(
                player_name=record.player_name,
                status='Returning Soon',
                reason=record.reason,
                expected_return=record.expected_return,
                source=record.source,
            )
            for record in injury_records
            if self._returns_soon(record.expected_return, fixture.kickoff_at)
        ]
        bench_depth = self._build_bench_depth_context(
            fixture=fixture,
            team_name=team_name,
            injuries=injury_records,
            suspensions=suspensions,
            lineup=lineup,
        )
        return AvailabilityContext(
            injuries=injury_records,
            suspensions=suspensions,
            returning_players=returning_players,
            expected_absences_summary=self._expected_absence_summary(
                injury_count=len(injury_records),
                suspension_count=len(suspensions),
            ),
            bench_depth=bench_depth,
        )

    def _build_bench_depth_context(
        self,
        *,
        fixture,
        team_name: str,
        injuries: list[AvailabilityRecord],
        suspensions: list[AvailabilityRecord],
        lineup: TeamLineup | None,
    ):
        builder = getattr(self._transfermarkt_dataset, 'build_bench_depth_context', None)
        if not callable(builder):
            return None
        unavailable_players = {
            record.player_name for record in [*injuries, *suspensions]
        }
        starting_players = {
            player.player_name for player in lineup.players
        } if lineup is not None else set()
        return builder(
            league_code=fixture.league_code,
            team_name=team_name,
            unavailable_players=unavailable_players,
            starting_players=starting_players,
        )

    def _expected_absence_summary(
        self,
        *,
        injury_count: int,
        suspension_count: int,
    ) -> str | None:
        parts = []
        if injury_count:
            label = 'injury' if injury_count == 1 else 'injuries'
            parts.append(f'{injury_count} {label}')
        if suspension_count:
            label = 'suspension' if suspension_count == 1 else 'suspensions'
            parts.append(f'{suspension_count} {label}')
        return ', '.join(parts) or None

    def _returns_soon(
        self,
        expected_return: str | None,
        kickoff_at: datetime,
    ) -> bool:
        if expected_return is None:
            return False
        try:
            return_date = date.fromisoformat(expected_return)
        except ValueError:
            return False
        days_until_return = (return_date - kickoff_at.astimezone(UTC).date()).days
        return 0 <= days_until_return <= 7

    def _build_environment_context(
        self,
        *,
        fixture,
        weather,
        include_travel: bool = True,
    ) -> EnvironmentContext:
        league = get_league(fixture.league_code)
        venue_reference = None
        if fixture.venue is not None and hasattr(self._reference_repository, 'get_venue_reference'):
            venue_reference = self._reference_repository.get_venue_reference(
                fixture.venue,
                league.country,
            )
        kickoff_local_time = self._localize_kickoff(
            fixture.kickoff_at,
            venue_reference.timezone if venue_reference is not None else None,
        )
        travel_builder = getattr(self._weather_client, 'build_away_travel_context', None)
        away_travel = None
        if include_travel and callable(travel_builder):
            away_travel = travel_builder(
                fixture=fixture,
                away_team_name=fixture.away_team,
            )
        source_names = {'fixture': fixture.source}
        if venue_reference is not None:
            source_names['venue'] = venue_reference.source
        if weather is not None:
            source_names['weather'] = weather.source
        if away_travel is not None:
            source_names['travel'] = away_travel.source
        home_rest_days = self._rest_days_for_team(
            fixture=fixture,
            team_id=fixture.home_team_id,
            team_name=fixture.home_team,
        )
        away_rest_days = self._rest_days_for_team(
            fixture=fixture,
            team_id=fixture.away_team_id,
            team_name=fixture.away_team,
        )
        if home_rest_days is not None or away_rest_days is not None:
            source_names['rest_days'] = 'fixture-cache'
        return EnvironmentContext(
            venue_name=fixture.venue,
            referee=fixture.referee,
            kickoff_local_time=kickoff_local_time,
            weather=weather,
            home_rest_days=home_rest_days,
            away_rest_days=away_rest_days,
            away_travel=away_travel,
            source_names=source_names,
        )

    def _rest_days_for_team(
        self,
        *,
        fixture,
        team_id: int | None,
        team_name: str,
    ) -> int | None:
        lookup = getattr(self._fixture_repository, 'get_latest_finished_for_team_before', None)
        if not callable(lookup):
            return None
        previous = lookup(
            league=fixture.league_code,
            team_id=team_id,
            team_name=team_name,
            before=fixture.kickoff_at,
        )
        if previous is None:
            return None
        return max(0, (fixture.kickoff_at.date() - previous.kickoff_at.date()).days)

    def _localize_kickoff(
        self,
        kickoff_at: datetime,
        timezone_name: str | None,
    ) -> datetime | None:
        if timezone_name is None:
            return None
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return None
        return kickoff_at.astimezone(zone)

    def _build_matchup_context(
        self,
        *,
        fixture,
        home: TeamEnrichment,
        away: TeamEnrichment,
        live_context: bool = True,
    ) -> MatchupTrendContext:
        statistics_fetcher = (
            getattr(self._api_context_client, 'fetch_team_statistics', None)
            if live_context
            else None
        )
        head_to_head_fetcher = (
            getattr(self._api_context_client, 'fetch_head_to_head', None)
            if live_context
            else None
        )
        home_split = None
        away_split = None
        head_to_head = None
        # API-Football splits/head-to-head degrade to None when the provider is
        # unavailable; the soccerdata-sourced home_trend/away_trend below remain
        # populated so expected_goals_from_snapshot can still price the fixture.
        try:
            if callable(statistics_fetcher):
                if fixture.home_team_id is not None:
                    home_split = statistics_fetcher(
                        team_id=fixture.home_team_id,
                        league_id=fixture.provider_league_id,
                        season=fixture.season,
                    )
                if fixture.away_team_id is not None:
                    away_split = statistics_fetcher(
                        team_id=fixture.away_team_id,
                        league_id=fixture.provider_league_id,
                        season=fixture.season,
                    )
            if (
                callable(head_to_head_fetcher)
                and fixture.home_team_id is not None
                and fixture.away_team_id is not None
            ):
                head_to_head = head_to_head_fetcher(
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    last=5,
                )
        except ApiFootballError as exc:
            _LOGGER.warning(
                'API-Football unavailable for fixture %s matchup context; '
                'degrading splits/head-to-head to None: %s',
                fixture.fixture_id,
                exc,
            )
            home_split = None
            away_split = None
            head_to_head = None
        return MatchupTrendContext(
            head_to_head=head_to_head,
            home_split=home_split,
            away_split=away_split,
            home_trend=self._build_team_trend(home),
            away_trend=self._build_team_trend(away),
        )

    def _build_team_trend(self, team: TeamEnrichment) -> TeamTrendSummary | None:
        recent_form = team.recent_form
        shot_summary = team.shot_summary
        if recent_form is None:
            return None
        set_piece_share = None
        if shot_summary is not None and shot_summary.shots > 0:
            set_piece_share = round(
                max(shot_summary.shots - shot_summary.open_play_shots, 0) / shot_summary.shots,
                2,
            )
        matches = recent_form.matches or 0
        if matches <= 0:
            return None
        return TeamTrendSummary(
            sample_size=matches,
            goals_for_per_match=round(recent_form.goals_for / matches, 2),
            xg_for_per_match=round(recent_form.xg_for / matches, 2),
            goals_against_per_match=round(recent_form.goals_against / matches, 2),
            xg_against_per_match=round(recent_form.xg_against / matches, 2),
            set_piece_shot_share=set_piece_share,
            source='soccerdata',
        )
