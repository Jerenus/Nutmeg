from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from nutmeg.config.team_catalog import load_team_catalog
from nutmeg.data.api_football import ApiFootballError
from nutmeg.data.soccerdata_client import SoccerDataClient, SoccerDataError
from nutmeg.domain.fixtures import Fixture, sample_fixtures
from nutmeg.domain.snapshot import (
    AvailabilityContext,
    AvailabilityRecord,
    BenchDepthContext,
    EnvironmentContext,
    HeadToHeadSummary,
    InjuryStatus,
    LineupPlayer,
    MatchupTrendContext,
    SoccerDataFixtureBundle,
    TeamEnrichment,
    TeamLineup,
    TeamMarketValue,
    TeamRecentForm,
    TeamSeasonMetrics,
    TeamShotSummary,
    TeamSplitSummary,
    TeamTrendSummary,
    TravelContext,
    VenueReference,
    WeatherContext,
)
from nutmeg.services.snapshot import FixtureNotFoundError, FixtureSnapshotService
from nutmeg.storage.reference_repository import ResolvedPlayerIdentity


class FakeSoccerDataBackend:
    def __init__(
        self,
        *,
        fbref_standard_team_stats: pd.DataFrame,
        fbref_shooting_team_stats: pd.DataFrame,
        understat_team_match_stats: pd.DataFrame,
        understat_shot_events: pd.DataFrame,
    ) -> None:
        self.fbref_standard_team_stats = fbref_standard_team_stats
        self.fbref_shooting_team_stats = fbref_shooting_team_stats
        self.understat_team_match_stats = understat_team_match_stats
        self.understat_shot_events = understat_shot_events

    def build_fbref_reader(self, **_: object):
        return FakeFBrefReader(
            standard_frame=self.fbref_standard_team_stats,
            shooting_frame=self.fbref_shooting_team_stats,
        )

    def build_understat_reader(self, **_: object):
        return FakeUnderstatReader(
            team_match_stats=self.understat_team_match_stats,
            shot_events=self.understat_shot_events,
        )


class FakeFBrefReader:
    def __init__(
        self,
        *,
        standard_frame: pd.DataFrame,
        shooting_frame: pd.DataFrame,
    ) -> None:
        self._standard_frame = standard_frame
        self._shooting_frame = shooting_frame

    def read_team_season_stats(self, stat_type: str) -> pd.DataFrame:
        if stat_type == 'standard':
            return self._standard_frame
        assert stat_type == 'shooting'
        return self._shooting_frame


class FakeUnderstatReader:
    def __init__(self, *, team_match_stats: pd.DataFrame, shot_events: pd.DataFrame) -> None:
        self._team_match_stats = team_match_stats
        self._shot_events = shot_events

    def read_team_match_stats(self) -> pd.DataFrame:
        return self._team_match_stats

    def read_shot_events(self, match_id: list[int]) -> pd.DataFrame:
        return self._shot_events[self._shot_events['game_id'].isin(match_id)].copy()


class FakeFixtureRepository:
    def __init__(
        self,
        fixture: Fixture | None,
        *,
        previous_by_team: dict[int | str, Fixture] | None = None,
    ) -> None:
        self._fixture = fixture
        self._previous_by_team = previous_by_team or {}

    def get_fixture(self, fixture_id: str) -> Fixture | None:
        if self._fixture and self._fixture.fixture_id == fixture_id:
            return self._fixture
        return None

    def get_latest_finished_for_team_before(
        self,
        *,
        league: str,
        team_id: int | None,
        team_name: str,
        before: datetime,
    ) -> Fixture | None:
        assert league == 'epl'
        assert before == self._fixture.kickoff_at
        return self._previous_by_team.get(team_id) or self._previous_by_team.get(team_name)


class FakeSoccerDataClient:
    def __init__(self, bundle: SoccerDataFixtureBundle) -> None:
        self._bundle = bundle

    def fetch_fixture_enrichment(
        self,
        *,
        fixture: Fixture,
        recent_matches: int = 5,
    ) -> SoccerDataFixtureBundle:
        assert fixture.fixture_id == 'epl-001'
        assert recent_matches == 5
        return self._bundle


class FakeTransfermarktDataset:
    def __init__(
        self,
        *,
        market_values: dict[str, TeamMarketValue],
        probable_lineups: dict[str, TeamLineup],
        bench_depths: dict[str, BenchDepthContext] | None = None,
    ) -> None:
        self._market_values = market_values
        self._probable_lineups = probable_lineups
        self._bench_depths = bench_depths or {}

    def fetch_team_market_value(self, league_code: str, team_name: str) -> TeamMarketValue | None:
        assert league_code == 'epl'
        return self._market_values.get(team_name)

    def build_probable_lineup(
        self,
        *,
        league_code: str,
        team_name: str,
        unavailable_players: set[str],
        recent_games: int = 5,
    ) -> TeamLineup | None:
        assert league_code == 'epl'
        assert recent_games == 5
        lineup = self._probable_lineups.get(team_name)
        if lineup is None:
            return None
        filtered_players = [
            player for player in lineup.players if player.player_name not in unavailable_players
        ]
        return TeamLineup(
            status=lineup.status,
            source=lineup.source,
            formation=lineup.formation,
            players=filtered_players,
        )

    def build_bench_depth_context(
        self,
        *,
        league_code: str,
        team_name: str,
        unavailable_players: set[str],
        starting_players: set[str],
    ) -> BenchDepthContext | None:
        assert league_code == 'epl'
        return self._bench_depths.get(team_name)


class FakeApiFootballContextClient:
    def __init__(
        self,
        *,
        injuries: dict[int, list[InjuryStatus]] | None = None,
        lineups: dict[int, TeamLineup] | None = None,
        sidelined: dict[int, list[AvailabilityRecord]] | None = None,
        team_statistics: dict[int, TeamSplitSummary] | None = None,
        head_to_head: HeadToHeadSummary | None = None,
    ) -> None:
        self._injuries = injuries or {}
        self._lineups = lineups or {}
        self._sidelined = sidelined or {}
        self._team_statistics = team_statistics or {}
        self._head_to_head = head_to_head

    def fetch_fixture_injuries(self, fixture_id: str) -> dict[int, list[InjuryStatus]]:
        assert fixture_id == 'epl-001'
        return self._injuries

    def fetch_fixture_lineups(self, fixture_id: str) -> dict[int, TeamLineup]:
        assert fixture_id == 'epl-001'
        return self._lineups

    def fetch_team_sidelined(
        self,
        team_id: int,
        season: int,
        *,
        as_of_date=None,
    ) -> list[AvailabilityRecord]:
        assert season == 2025
        assert as_of_date is None or str(as_of_date).startswith('202')
        return self._sidelined.get(team_id, [])

    def fetch_team_statistics(
        self,
        *,
        team_id: int,
        league_id: int,
        season: int,
    ) -> TeamSplitSummary | None:
        assert league_id == 0 or league_id == 39
        assert season == 2025
        return self._team_statistics.get(team_id)

    def fetch_head_to_head(
        self,
        *,
        home_team_id: int,
        away_team_id: int,
        last: int = 5,
    ) -> HeadToHeadSummary | None:
        assert home_team_id == 42
        assert away_team_id == 148
        assert last == 5
        return self._head_to_head


class FakeWeatherClient:
    def __init__(
        self,
        weather: WeatherContext | None = None,
        travel: TravelContext | None = None,
    ) -> None:
        self._weather = weather
        self._travel = travel

    def get_fixture_weather(self, fixture: Fixture) -> WeatherContext | None:
        assert fixture.fixture_id == 'epl-001'
        return self._weather

    def build_away_travel_context(
        self,
        *,
        fixture: Fixture,
        away_team_name: str,
    ) -> TravelContext | None:
        assert fixture.fixture_id == 'epl-001'
        assert away_team_name == 'Tottenham Hotspur'
        return self._travel


class FakeReferenceRepository:
    def __init__(self, venue_reference: VenueReference | None = None) -> None:
        self._venue_reference = venue_reference

    def resolve_player_identity(
        self,
        *,
        league_code: str,
        team_name: str,
        provider: str,
        player_name: str,
        position: str | None = None,
        provider_player_id: str | None = None,
    ) -> ResolvedPlayerIdentity | None:
        if league_code != 'epl' or team_name != 'Arsenal':
            return None
        if player_name in {'Gabriel', 'Gabriel Magalhães', 'Gabriel Magalhaes'}:
            return ResolvedPlayerIdentity(
                identity_id='epl:arsenal:gabriel-magalhaes',
                canonical_name='Gabriel Magalhaes',
                match_confidence='catalog',
            )
        return None

    def get_venue_reference(
        self,
        venue_name: str,
        country_name: str | None = None,
    ) -> VenueReference | None:
        assert venue_name == 'Emirates Stadium'
        assert country_name in {None, 'England'}
        return self._venue_reference


def test_soccerdata_client_normalizes_fixture_enrichment() -> None:
    client = SoccerDataClient(
        team_catalog=load_team_catalog(),
        backend=FakeSoccerDataBackend(
            fbref_standard_team_stats=_fbref_standard_team_stats(),
            fbref_shooting_team_stats=_fbref_shooting_team_stats(),
            understat_team_match_stats=_understat_match_stats(),
            understat_shot_events=_understat_shot_events(),
        ),
    )

    bundle = client.fetch_fixture_enrichment(
        fixture=sample_fixtures('epl', season=2025)[0],
        recent_matches=2,
    )

    assert bundle.home.source_names['understat'] == 'Arsenal'
    assert bundle.away.source_names['understat'] == 'Tottenham'
    assert bundle.home.season_metrics == TeamSeasonMetrics(
        matches=32.0,
        goals=58.0,
        shots=420.0,
        shots_on_target=160.0,
        xg=54.2,
        non_penalty_xg=49.8,
    )
    assert bundle.home.recent_form == TeamRecentForm(
        matches=2,
        wins=1,
        draws=1,
        losses=0,
        points=4,
        expected_points=4.1,
        goals_for=3.0,
        goals_against=2.0,
        xg_for=3.4,
        xg_against=1.8,
    )
    assert bundle.home.shot_summary == TeamShotSummary(
        shots=5,
        goals=1,
        total_xg=1.15,
        open_play_shots=4,
    )


def test_soccerdata_client_rejects_unsupported_leagues() -> None:
    fixture = replace(
        sample_fixtures('epl', season=2025)[0],
        fixture_id='ucl-001',
        league_code='ucl',
        season=2025,
    )
    client = SoccerDataClient(
        team_catalog=load_team_catalog(),
        backend=FakeSoccerDataBackend(
            fbref_standard_team_stats=_fbref_standard_team_stats(),
            fbref_shooting_team_stats=_fbref_shooting_team_stats(),
            understat_team_match_stats=_understat_match_stats(),
            understat_shot_events=_understat_shot_events(),
        ),
    )

    with pytest.raises(SoccerDataError, match='does not have a supported soccerdata mapping'):
        client.fetch_fixture_enrichment(fixture=fixture)


def test_soccerdata_client_returns_null_for_missing_fbref_xg_columns() -> None:
    client = SoccerDataClient(
        team_catalog=load_team_catalog(),
        backend=FakeSoccerDataBackend(
            fbref_standard_team_stats=_fbref_standard_without_xg(),
            fbref_shooting_team_stats=_fbref_shooting_team_stats(),
            understat_team_match_stats=_understat_match_stats(),
            understat_shot_events=_understat_shot_events(),
        ),
    )

    bundle = client.fetch_fixture_enrichment(
        fixture=sample_fixtures('epl', season=2025)[0],
        recent_matches=2,
    )

    assert bundle.home.season_metrics is not None
    assert bundle.home.season_metrics.xg is None
    assert bundle.home.season_metrics.non_penalty_xg is None


def test_fixture_snapshot_service_builds_snapshot_with_confirmed_lineups() -> None:
    fixture = sample_fixtures('epl', season=2025)[0]
    bundle = SoccerDataFixtureBundle(
        league_code='epl',
        season=fixture.season,
        home=TeamEnrichment(
            canonical_name='Arsenal',
            source_names={'fbref': 'Arsenal', 'understat': 'Arsenal'},
            season_metrics=TeamSeasonMetrics(
                matches=32.0,
                goals=58.0,
                shots=420.0,
                shots_on_target=160.0,
                xg=54.2,
                non_penalty_xg=49.8,
            ),
            recent_form=TeamRecentForm(
                matches=5,
                wins=3,
                draws=1,
                losses=1,
                points=10,
                expected_points=9.1,
                goals_for=9.0,
                goals_against=5.0,
                xg_for=8.4,
                xg_against=5.3,
            ),
            shot_summary=TeamShotSummary(
                shots=60,
                goals=8,
                total_xg=8.8,
                open_play_shots=48,
            ),
            market_value=None,
            injuries=[],
            lineup=None,
        ),
        away=TeamEnrichment(
            canonical_name='Tottenham Hotspur',
            source_names={'fbref': 'Tottenham Hotspur', 'understat': 'Tottenham'},
            season_metrics=TeamSeasonMetrics(
                matches=32.0,
                goals=56.0,
                shots=390.0,
                shots_on_target=150.0,
                xg=51.7,
                non_penalty_xg=47.3,
            ),
            recent_form=TeamRecentForm(
                matches=5,
                wins=2,
                draws=1,
                losses=2,
                points=7,
                expected_points=7.4,
                goals_for=8.0,
                goals_against=7.0,
                xg_for=7.8,
                xg_against=6.9,
            ),
            shot_summary=TeamShotSummary(
                shots=55,
                goals=7,
                total_xg=7.6,
                open_play_shots=43,
            ),
            market_value=None,
            injuries=[],
            lineup=None,
        ),
    )
    service = FixtureSnapshotService(
        fixture_repository=FakeFixtureRepository(fixture),
        soccerdata_client=FakeSoccerDataClient(bundle),
        transfermarkt_dataset=FakeTransfermarktDataset(
            market_values={
                'Arsenal': TeamMarketValue(
                    source='transfermarkt-datasets',
                    total_market_value_eur=800000000,
                    top_players=[('Bukayo Saka', 140000000)],
                ),
                'Tottenham Hotspur': TeamMarketValue(
                    source='transfermarkt-datasets',
                    total_market_value_eur=650000000,
                    top_players=[('James Maddison', 70000000)],
                ),
            },
            probable_lineups={},
        ),
        api_context_client=FakeApiFootballContextClient(
            injuries={
                42: [
                    InjuryStatus(
                        player_name='Bukayo Saka',
                        status='Injured',
                        reason='Hamstring',
                        expected_return=None,
                        source='api-football',
                    )
                ]
            },
            lineups={
                42: TeamLineup(
                    status='confirmed',
                    source='api-football',
                    formation='4-3-3',
                    players=[
                        LineupPlayer(
                            player_name='Kai Havertz',
                            position='F',
                            shirt_number='29',
                            role='starter',
                            captain=False,
                        )
                    ],
                ),
                148: TeamLineup(
                    status='confirmed',
                    source='api-football',
                    formation='4-2-3-1',
                    players=[
                        LineupPlayer(
                            player_name='Son Heung-min',
                            position='F',
                            shirt_number='7',
                            role='starter',
                            captain=True,
                        )
                    ],
                ),
            },
        ),
        reference_repository=FakeReferenceRepository(),
        weather_client=FakeWeatherClient(),
    )

    snapshot = service.build_snapshot('epl-001')

    assert snapshot.home.market_value is not None
    assert snapshot.home.market_value.total_market_value_eur == 800000000
    assert snapshot.home.injuries[0].player_name == 'Bukayo Saka'
    assert snapshot.home.lineup is not None
    assert snapshot.home.lineup.status == 'confirmed'
    assert snapshot.away.lineup is not None
    assert snapshot.away.lineup.status == 'confirmed'
    assert snapshot.deferred_sections == []


def test_fixture_snapshot_service_local_context_skips_live_context_clients() -> None:
    fixture = sample_fixtures('epl', season=2025)[0]
    bundle = SoccerDataFixtureBundle(
        league_code='epl',
        season=fixture.season,
        home=_empty_team_enrichment(fixture.home_team),
        away=_empty_team_enrichment(fixture.away_team),
    )

    class RaisingApiFootballContextClient:
        def fetch_fixture_injuries(self, fixture_id: str):
            raise AssertionError(f'unexpected injuries fetch for {fixture_id}')

        def fetch_fixture_lineups(self, fixture_id: str):
            raise AssertionError(f'unexpected lineups fetch for {fixture_id}')

        def fetch_team_sidelined(self, *args, **kwargs):
            raise AssertionError('unexpected sidelined fetch')

        def fetch_team_statistics(self, *args, **kwargs):
            raise AssertionError('unexpected statistics fetch')

        def fetch_head_to_head(self, *args, **kwargs):
            raise AssertionError('unexpected head-to-head fetch')

    service = FixtureSnapshotService(
        fixture_repository=FakeFixtureRepository(fixture),
        soccerdata_client=FakeSoccerDataClient(bundle),
        transfermarkt_dataset=FakeTransfermarktDataset(
            market_values={},
            probable_lineups={},
        ),
        api_context_client=RaisingApiFootballContextClient(),
        reference_repository=FakeReferenceRepository(),
        weather_client=FakeWeatherClient(),
    )

    snapshot = service.build_snapshot('epl-001', live_context=False)

    assert snapshot.home.injuries == []
    assert snapshot.away.injuries == []
    assert snapshot.home.availability is not None
    assert snapshot.home.availability.suspensions == []
    assert snapshot.matchup is not None
    assert snapshot.matchup.head_to_head is None
    assert snapshot.matchup.home_split is None
    assert snapshot.matchup.away_split is None
    assert snapshot.environment is not None
    assert snapshot.environment.weather is None


def test_fixture_snapshot_service_falls_back_to_probable_lineups() -> None:
    fixture = sample_fixtures('epl', season=2025)[0]
    bundle = SoccerDataFixtureBundle(
        league_code='epl',
        season=fixture.season,
        home=_empty_team_enrichment('Arsenal'),
        away=_empty_team_enrichment('Tottenham Hotspur'),
    )
    service = FixtureSnapshotService(
        fixture_repository=FakeFixtureRepository(fixture),
        soccerdata_client=FakeSoccerDataClient(bundle),
        transfermarkt_dataset=FakeTransfermarktDataset(
            market_values={},
            probable_lineups={
                'Arsenal': TeamLineup(
                    status='probable',
                    source='transfermarkt-datasets',
                    formation='4-3-3',
                    players=[
                        LineupPlayer(
                            player_name='Martin Odegaard',
                            position='M',
                            shirt_number='8',
                            role='starter',
                            captain=True,
                        ),
                        LineupPlayer(
                            player_name='Unavailable Player',
                            position='F',
                            shirt_number='9',
                            role='starter',
                            captain=False,
                        ),
                    ],
                ),
                'Tottenham Hotspur': TeamLineup(
                    status='probable',
                    source='transfermarkt-datasets',
                    formation='4-2-3-1',
                    players=[
                        LineupPlayer(
                            player_name='Son Heung-min',
                            position='F',
                            shirt_number='7',
                            role='starter',
                            captain=True,
                        )
                    ],
                ),
            },
        ),
        api_context_client=FakeApiFootballContextClient(
            injuries={
                42: [
                    InjuryStatus(
                        player_name='Unavailable Player',
                        status='Injured',
                        reason='Ankle',
                        expected_return=None,
                        source='api-football',
                    )
                ]
            },
            lineups={},
        ),
        reference_repository=FakeReferenceRepository(),
        weather_client=FakeWeatherClient(),
    )

    snapshot = service.build_snapshot('epl-001')

    assert snapshot.home.lineup is not None
    assert snapshot.home.lineup.status == 'probable'
    assert [player.player_name for player in snapshot.home.lineup.players] == ['Martin Odegaard']
    assert snapshot.away.lineup is not None
    assert snapshot.away.lineup.status == 'probable'


def test_fixture_snapshot_service_excludes_probable_lineup_by_canonical_identity() -> None:
    fixture = sample_fixtures('epl', season=2025)[0]
    bundle = SoccerDataFixtureBundle(
        league_code='epl',
        season=fixture.season,
        home=_empty_team_enrichment('Arsenal'),
        away=_empty_team_enrichment('Tottenham Hotspur'),
    )
    service = FixtureSnapshotService(
        fixture_repository=FakeFixtureRepository(fixture),
        soccerdata_client=FakeSoccerDataClient(bundle),
        transfermarkt_dataset=FakeTransfermarktDataset(
            market_values={},
            probable_lineups={
                'Arsenal': TeamLineup(
                    status='probable',
                    source='transfermarkt-datasets',
                    formation='4-3-3',
                    players=[
                        LineupPlayer(
                            player_name='Gabriel',
                            position='D',
                            shirt_number='6',
                            role='starter',
                            captain=False,
                        ),
                        LineupPlayer(
                            player_name='Martin Odegaard',
                            position='M',
                            shirt_number='8',
                            role='starter',
                            captain=True,
                        ),
                    ],
                ),
            },
        ),
        api_context_client=FakeApiFootballContextClient(
            injuries={
                42: [
                    InjuryStatus(
                        player_name='Gabriel Magalhães',
                        status='Injured',
                        reason='Knee',
                        expected_return=None,
                        source='api-football',
                    )
                ]
            },
            lineups={},
        ),
        reference_repository=FakeReferenceRepository(),
        weather_client=FakeWeatherClient(),
    )

    snapshot = service.build_snapshot('epl-001')

    assert snapshot.home.lineup is not None
    assert [player.player_name for player in snapshot.home.lineup.players] == ['Martin Odegaard']


def test_fixture_snapshot_service_raises_when_fixture_is_missing() -> None:
    bundle = SoccerDataFixtureBundle(
        league_code='epl',
        season=2025,
        home=_empty_team_enrichment('Arsenal'),
        away=_empty_team_enrichment('Tottenham Hotspur'),
    )
    service = FixtureSnapshotService(
        fixture_repository=FakeFixtureRepository(None),
        soccerdata_client=FakeSoccerDataClient(bundle),
        transfermarkt_dataset=FakeTransfermarktDataset(market_values={}, probable_lineups={}),
        api_context_client=FakeApiFootballContextClient(),
        reference_repository=FakeReferenceRepository(),
        weather_client=FakeWeatherClient(),
    )

    with pytest.raises(FixtureNotFoundError, match='missing-001'):
        service.build_snapshot('missing-001')



def test_fixture_snapshot_service_computes_rest_days_from_historical_fixture_cache() -> None:
    fixture = replace(
        sample_fixtures('epl', season=2025)[0],
        provider_league_id=39,
        kickoff_at=datetime(2026, 4, 25, 14, tzinfo=UTC),
        home_team_id=42,
        away_team_id=148,
    )
    previous_home = replace(
        fixture,
        fixture_id='arsenal-prev',
        kickoff_at=fixture.kickoff_at - pd.Timedelta(days=5),
        status_short='FT',
    )
    previous_away = replace(
        fixture,
        fixture_id='spurs-prev',
        kickoff_at=fixture.kickoff_at - pd.Timedelta(days=3),
        home_team_id=77,
        away_team_id=148,
        home_team='Chelsea',
        away_team=fixture.away_team,
        status_short='FT',
    )
    bundle = SoccerDataFixtureBundle(
        league_code='epl',
        season=fixture.season,
        home=TeamEnrichment(
            canonical_name=fixture.home_team,
            source_names={},
            season_metrics=None,
            recent_form=None,
            shot_summary=None,
            market_value=None,
            injuries=[],
            lineup=None,
        ),
        away=TeamEnrichment(
            canonical_name=fixture.away_team,
            source_names={},
            season_metrics=None,
            recent_form=None,
            shot_summary=None,
            market_value=None,
            injuries=[],
            lineup=None,
        ),
    )
    service = FixtureSnapshotService(
        fixture_repository=FakeFixtureRepository(
            fixture,
            previous_by_team={42: previous_home, 148: previous_away},
        ),
        soccerdata_client=FakeSoccerDataClient(bundle),
        transfermarkt_dataset=FakeTransfermarktDataset(market_values={}, probable_lineups={}),
        api_context_client=FakeApiFootballContextClient(),
        reference_repository=FakeReferenceRepository(),
        weather_client=FakeWeatherClient(),
    )

    snapshot = service.build_snapshot('epl-001')

    assert snapshot.environment is not None
    assert snapshot.environment.home_rest_days == 5
    assert snapshot.environment.away_rest_days == 3

def test_fixture_snapshot_service_builds_environment_availability_and_matchup_context() -> None:
    fixture = replace(
        sample_fixtures('epl', season=2025)[0],
        provider_league_id=39,
        kickoff_at=datetime(2026, 4, 25, 14, tzinfo=UTC),
        round_name='Regular Season - 34',
        venue='Emirates Stadium',
        referee='Michael Oliver',
    )
    bundle = SoccerDataFixtureBundle(
        league_code='epl',
        season=fixture.season,
        home=TeamEnrichment(
            canonical_name='Arsenal',
            source_names={'fbref': 'Arsenal', 'understat': 'Arsenal'},
            season_metrics=None,
            recent_form=TeamRecentForm(
                matches=5,
                wins=3,
                draws=1,
                losses=1,
                points=10,
                expected_points=9.0,
                goals_for=9.0,
                goals_against=4.0,
                xg_for=8.4,
                xg_against=4.7,
            ),
            shot_summary=TeamShotSummary(
                shots=50,
                goals=8,
                total_xg=7.9,
                open_play_shots=38,
            ),
            market_value=None,
            injuries=[],
            lineup=None,
        ),
        away=TeamEnrichment(
            canonical_name='Tottenham Hotspur',
            source_names={'fbref': 'Tottenham Hotspur', 'understat': 'Tottenham'},
            season_metrics=None,
            recent_form=TeamRecentForm(
                matches=5,
                wins=2,
                draws=1,
                losses=2,
                points=7,
                expected_points=7.2,
                goals_for=7.0,
                goals_against=6.0,
                xg_for=7.1,
                xg_against=6.4,
            ),
            shot_summary=TeamShotSummary(
                shots=46,
                goals=7,
                total_xg=6.8,
                open_play_shots=31,
            ),
            market_value=None,
            injuries=[],
            lineup=None,
        ),
    )
    service = FixtureSnapshotService(
        fixture_repository=FakeFixtureRepository(fixture),
        soccerdata_client=FakeSoccerDataClient(bundle),
        transfermarkt_dataset=FakeTransfermarktDataset(
            market_values={},
            probable_lineups={},
            bench_depths={
                'Arsenal': BenchDepthContext(
                    bench_market_value_eur=210000000,
                    available_players=15,
                    label='strong',
                    source='transfermarkt-datasets',
                )
            },
        ),
        api_context_client=FakeApiFootballContextClient(
            injuries={
                42: [
                    InjuryStatus(
                        player_name='Bukayo Saka',
                        status='Injured',
                        reason='Hamstring',
                        expected_return='2026-04-28',
                        source='api-football',
                    )
                ]
            },
            lineups={},
            sidelined={
                42: [
                    AvailabilityRecord(
                        player_name='William Saliba',
                        status='Suspended',
                        reason='Accumulated cards',
                        expected_return='2026-04-30',
                        source='api-football',
                    )
                ]
            },
            team_statistics={
                42: TeamSplitSummary(
                    home_points_per_match=2.2,
                    away_points_per_match=1.4,
                    home_goals_for_per_match=2.1,
                    away_goals_for_per_match=1.5,
                    source='api-football',
                ),
                148: TeamSplitSummary(
                    home_points_per_match=1.9,
                    away_points_per_match=1.3,
                    home_goals_for_per_match=2.0,
                    away_goals_for_per_match=1.4,
                    source='api-football',
                ),
            },
            head_to_head=HeadToHeadSummary(
                matches=5,
                home_wins=3,
                draws=1,
                away_wins=1,
                source='api-football',
            ),
        ),
        reference_repository=FakeReferenceRepository(
            venue_reference=VenueReference(
                venue_key='emirates-stadium-england',
                venue_name='Emirates Stadium',
                country_name='England',
                latitude=51.555,
                longitude=-0.1086,
                timezone='Europe/London',
                source='open-meteo',
            )
        ),
        weather_client=FakeWeatherClient(
            weather=WeatherContext(
                forecast_at=datetime(2026, 4, 25, 8, 0, tzinfo=UTC),
                temperature_c=14.2,
                precipitation_probability=20,
                wind_speed_kph=12.8,
                weather_code=3,
                source='open-meteo',
            ),
            travel=TravelContext(
                distance_km=10.4,
                bucket='short-haul',
                source='open-meteo',
            ),
        ),
    )

    snapshot = service.build_snapshot('epl-001')

    assert snapshot.environment == EnvironmentContext(
        venue_name='Emirates Stadium',
        referee='Michael Oliver',
        kickoff_local_time=fixture.kickoff_at.astimezone(ZoneInfo('Europe/London')),
        weather=WeatherContext(
            forecast_at=datetime(2026, 4, 25, 8, 0, tzinfo=UTC),
            temperature_c=14.2,
            precipitation_probability=20,
            wind_speed_kph=12.8,
            weather_code=3,
            source='open-meteo',
        ),
        home_rest_days=None,
        away_rest_days=None,
        away_travel=TravelContext(
            distance_km=10.4,
            bucket='short-haul',
            source='open-meteo',
        ),
        source_names=snapshot.environment.source_names,
    )
    assert snapshot.home.availability == AvailabilityContext(
        injuries=[
            AvailabilityRecord(
                player_name='Bukayo Saka',
                status='Injured',
                reason='Hamstring',
                expected_return='2026-04-28',
                source='api-football',
            )
        ],
        suspensions=[
            AvailabilityRecord(
                player_name='William Saliba',
                status='Suspended',
                reason='Accumulated cards',
                expected_return='2026-04-30',
                source='api-football',
            )
        ],
        returning_players=[
            AvailabilityRecord(
                player_name='Bukayo Saka',
                status='Returning Soon',
                reason='Hamstring',
                expected_return='2026-04-28',
                source='api-football',
            )
        ],
        expected_absences_summary='1 injury, 1 suspension',
        bench_depth=BenchDepthContext(
            bench_market_value_eur=210000000,
            available_players=15,
            label='strong',
            source='transfermarkt-datasets',
        ),
    )
    assert snapshot.matchup == MatchupTrendContext(
        head_to_head=HeadToHeadSummary(
            matches=5,
            home_wins=3,
            draws=1,
            away_wins=1,
            source='api-football',
        ),
        home_split=TeamSplitSummary(
            home_points_per_match=2.2,
            away_points_per_match=1.4,
            home_goals_for_per_match=2.1,
            away_goals_for_per_match=1.5,
            source='api-football',
        ),
        away_split=TeamSplitSummary(
            home_points_per_match=1.9,
            away_points_per_match=1.3,
            home_goals_for_per_match=2.0,
            away_goals_for_per_match=1.4,
            source='api-football',
        ),
        home_trend=TeamTrendSummary(
            sample_size=5,
            goals_for_per_match=1.8,
            xg_for_per_match=1.68,
            goals_against_per_match=0.8,
            xg_against_per_match=0.94,
            set_piece_shot_share=0.24,
            source='soccerdata',
        ),
        away_trend=TeamTrendSummary(
            sample_size=5,
            goals_for_per_match=1.4,
            xg_for_per_match=1.42,
            goals_against_per_match=1.2,
            xg_against_per_match=1.28,
            set_piece_shot_share=0.33,
            source='soccerdata',
        ),
    )


def test_fixture_snapshot_service_degrades_to_soccerdata_when_api_football_unavailable(
    caplog,
) -> None:
    from nutmeg.models.dixon_coles import expected_goals_from_snapshot

    fixture = sample_fixtures('epl', season=2025)[0]
    bundle = SoccerDataFixtureBundle(
        league_code='epl',
        season=fixture.season,
        home=TeamEnrichment(
            canonical_name='Arsenal',
            source_names={'fbref': 'Arsenal', 'understat': 'Arsenal'},
            season_metrics=None,
            recent_form=TeamRecentForm(
                matches=5,
                wins=3,
                draws=1,
                losses=1,
                points=10,
                expected_points=9.0,
                goals_for=9.0,
                goals_against=4.0,
                xg_for=8.4,
                xg_against=4.7,
            ),
            shot_summary=TeamShotSummary(
                shots=50,
                goals=8,
                total_xg=7.9,
                open_play_shots=38,
            ),
            market_value=None,
            injuries=[],
            lineup=None,
        ),
        away=TeamEnrichment(
            canonical_name='Tottenham Hotspur',
            source_names={'fbref': 'Tottenham Hotspur', 'understat': 'Tottenham'},
            season_metrics=None,
            recent_form=TeamRecentForm(
                matches=5,
                wins=2,
                draws=1,
                losses=2,
                points=7,
                expected_points=7.2,
                goals_for=7.0,
                goals_against=6.0,
                xg_for=7.1,
                xg_against=6.4,
            ),
            shot_summary=TeamShotSummary(
                shots=46,
                goals=7,
                total_xg=6.8,
                open_play_shots=31,
            ),
            market_value=None,
            injuries=[],
            lineup=None,
        ),
    )

    class QuotaExhaustedApiFootballClient:
        """Every API-Football call raises, simulating an exhausted daily quota."""

        def fetch_fixture_injuries(self, fixture_id: str):
            raise ApiFootballError('API-Football rate limit exceeded (HTTP 429).')

        def fetch_fixture_lineups(self, fixture_id: str):
            raise ApiFootballError('API-Football rate limit exceeded (HTTP 429).')

        def fetch_team_sidelined(self, *args, **kwargs):
            raise ApiFootballError('API-Football rate limit exceeded (HTTP 429).')

        def fetch_team_statistics(self, *args, **kwargs):
            raise ApiFootballError('API-Football rate limit exceeded (HTTP 429).')

        def fetch_head_to_head(self, *args, **kwargs):
            raise ApiFootballError('API-Football rate limit exceeded (HTTP 429).')

    service = FixtureSnapshotService(
        fixture_repository=FakeFixtureRepository(fixture),
        soccerdata_client=FakeSoccerDataClient(bundle),
        transfermarkt_dataset=FakeTransfermarktDataset(
            market_values={},
            probable_lineups={},
        ),
        api_context_client=QuotaExhaustedApiFootballClient(),
        reference_repository=FakeReferenceRepository(),
        weather_client=FakeWeatherClient(),
    )

    with caplog.at_level('WARNING', logger='nutmeg.services.snapshot'):
        snapshot = service.build_snapshot('epl-001')

    # degradation is recorded as a warning rather than silently swallowed.
    assert any(
        'API-Football unavailable' in record.message
        for record in caplog.records
    )

    # soccerdata-sourced matchup trends remain populated despite API-Football failure.
    assert snapshot.matchup is not None
    assert snapshot.matchup.home_trend is not None
    assert snapshot.matchup.home_trend.source == 'soccerdata'
    assert snapshot.matchup.away_trend is not None
    assert snapshot.matchup.away_trend.source == 'soccerdata'
    # API-Football-sourced enrichment degrades to empty rather than aborting.
    assert snapshot.matchup.head_to_head is None
    assert snapshot.matchup.home_split is None
    assert snapshot.matchup.away_split is None
    assert snapshot.home.injuries == []
    assert snapshot.away.injuries == []
    # the model side still prices from the soccerdata matchup trends.
    expected_goals = expected_goals_from_snapshot(snapshot)
    assert expected_goals.source == 'recent-xg-matchup'


def _fbref_standard_team_stats() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            ('ENG-Premier League', '2025', 'Arsenal'),
            ('ENG-Premier League', '2025', 'Tottenham Hotspur'),
        ],
        names=['league', 'season', 'team'],
    )
    columns = pd.MultiIndex.from_tuples(
        [
            ('Playing Time', '90s'),
            ('Standard', 'Gls'),
            ('Expected', 'xG'),
            ('Expected', 'npxG'),
        ]
    )
    return pd.DataFrame(
        [
            [32.0, 58.0, 54.2, 49.8],
            [32.0, 56.0, 51.7, 47.3],
        ],
        index=index,
        columns=columns,
    )


def _fbref_shooting_team_stats() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            ('ENG-Premier League', '2025', 'Arsenal'),
            ('ENG-Premier League', '2025', 'Tottenham Hotspur'),
        ],
        names=['league', 'season', 'team'],
    )
    columns = pd.MultiIndex.from_tuples(
        [
            ('Standard', 'Sh'),
            ('Standard', 'SoT'),
        ]
    )
    return pd.DataFrame(
        [
            [420.0, 160.0],
            [390.0, 150.0],
        ],
        index=index,
        columns=columns,
    )


def _fbref_standard_without_xg() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            ('ENG-Premier League', '2025', 'Arsenal'),
            ('ENG-Premier League', '2025', 'Tottenham Hotspur'),
        ],
        names=['league', 'season', 'team'],
    )
    columns = pd.MultiIndex.from_tuples(
        [
            ('Playing Time', '90s'),
            ('Performance', 'Gls'),
        ]
    )
    return pd.DataFrame(
        [
            [32.0, 58.0],
            [32.0, 56.0],
        ],
        index=index,
        columns=columns,
    )


def _understat_match_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                'date': datetime(2026, 4, 10, tzinfo=UTC),
                'game_id': 101,
                'home_team': 'Arsenal',
                'away_team': 'Chelsea',
                'home_goals': 2.0,
                'away_goals': 1.0,
                'home_points': 3.0,
                'away_points': 0.0,
                'home_expected_points': 2.6,
                'away_expected_points': 0.3,
                'home_xg': 2.0,
                'away_xg': 0.7,
            },
            {
                'date': datetime(2026, 4, 16, tzinfo=UTC),
                'game_id': 102,
                'home_team': 'Liverpool',
                'away_team': 'Arsenal',
                'home_goals': 1.0,
                'away_goals': 1.0,
                'home_points': 1.0,
                'away_points': 1.0,
                'home_expected_points': 1.1,
                'away_expected_points': 1.5,
                'home_xg': 1.1,
                'away_xg': 1.4,
            },
            {
                'date': datetime(2026, 4, 11, tzinfo=UTC),
                'game_id': 201,
                'home_team': 'Tottenham',
                'away_team': 'Brighton',
                'home_goals': 1.0,
                'away_goals': 2.0,
                'home_points': 0.0,
                'away_points': 3.0,
                'home_expected_points': 1.2,
                'away_expected_points': 1.4,
                'home_xg': 1.3,
                'away_xg': 1.5,
            },
            {
                'date': datetime(2026, 4, 18, tzinfo=UTC),
                'game_id': 202,
                'home_team': 'Aston Villa',
                'away_team': 'Tottenham',
                'home_goals': 0.0,
                'away_goals': 3.0,
                'home_points': 0.0,
                'away_points': 3.0,
                'home_expected_points': 0.8,
                'away_expected_points': 2.1,
                'home_xg': 0.9,
                'away_xg': 2.2,
            },
        ]
    )


def _understat_shot_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                'game_id': 101,
                'team': 'Arsenal',
                'result': 'Goal',
                'situation': 'OpenPlay',
                'xg': 0.45,
            },
            {
                'game_id': 101,
                'team': 'Arsenal',
                'result': 'SavedShot',
                'situation': 'OpenPlay',
                'xg': 0.12,
            },
            {
                'game_id': 101,
                'team': 'Arsenal',
                'result': 'MissedShots',
                'situation': 'SetPiece',
                'xg': 0.08,
            },
            {
                'game_id': 102,
                'team': 'Arsenal',
                'result': 'BlockedShot',
                'situation': 'OpenPlay',
                'xg': 0.20,
            },
            {
                'game_id': 102,
                'team': 'Arsenal',
                'result': 'SavedShot',
                'situation': 'OpenPlay',
                'xg': 0.30,
            },
            {
                'game_id': 201,
                'team': 'Tottenham',
                'result': 'Goal',
                'situation': 'OpenPlay',
                'xg': 0.36,
            },
            {
                'game_id': 201,
                'team': 'Tottenham',
                'result': 'SavedShot',
                'situation': 'OpenPlay',
                'xg': 0.10,
            },
            {
                'game_id': 202,
                'team': 'Tottenham',
                'result': 'Goal',
                'situation': 'OpenPlay',
                'xg': 0.52,
            },
            {
                'game_id': 202,
                'team': 'Tottenham',
                'result': 'BlockedShot',
                'situation': 'OpenPlay',
                'xg': 0.17,
            },
        ]
    )


def _empty_team_enrichment(team_name: str) -> TeamEnrichment:
    return TeamEnrichment(
        canonical_name=team_name,
        source_names={'fbref': team_name, 'understat': team_name},
        season_metrics=None,
        recent_form=None,
        shot_summary=None,
        market_value=None,
        injuries=[],
        lineup=None,
    )
