from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import clear_settings_cache
from nutmeg.data.api_football import ApiFootballClient, ApiQuota, FixtureBatch
from nutmeg.data.open_meteo import OpenMeteoClient
from nutmeg.data.soccerdata_client import SoccerDataClient, SoccerDataFixtureBundle
from nutmeg.data.transfermarkt import TransfermarktDataset
from nutmeg.domain.fixtures import sample_fixtures
from nutmeg.domain.snapshot import (
    AvailabilityContext,
    AvailabilityRecord,
    BenchDepthContext,
    EnvironmentContext,
    FixtureSnapshot,
    HeadToHeadSummary,
    InjuryStatus,
    LineupPlayer,
    MatchupTrendContext,
    TeamEnrichment,
    TeamLineup,
    TeamMarketValue,
    TeamRecentForm,
    TeamSeasonMetrics,
    TeamShotSummary,
    TeamSplitSummary,
    TeamTrendSummary,
    TravelContext,
    WeatherContext,
)
from nutmeg.interfaces.cli import app

runner = CliRunner()


def _stub_context_providers(monkeypatch) -> None:
    monkeypatch.setattr(OpenMeteoClient, "get_fixture_weather", lambda self, fixture: None)
    monkeypatch.setattr(
        OpenMeteoClient,
        "build_away_travel_context",
        lambda self, *, fixture, away_team_name: None,
    )
    monkeypatch.setattr(
        ApiFootballClient,
        "fetch_team_sidelined",
        lambda self, team_id, season, as_of_date=None: [],
    )
    monkeypatch.setattr(
        ApiFootballClient,
        "fetch_team_statistics",
        lambda self, *, team_id, league_id, season: None,
    )
    monkeypatch.setattr(
        ApiFootballClient,
        "fetch_head_to_head",
        lambda self, *, home_team_id, away_team_id, last=5: None,
    )


def test_doctor_reports_ready_workflow_and_harness() -> None:
    result = runner.invoke(app, ["doctor", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["workflow"]["verdict"] == "READY"
    assert payload["harness"]["feature_list_present"] is True
    assert payload["app"]["default_user_id"] == "owner"


def test_demo_fixtures_command_returns_fixture_rows() -> None:
    result = runner.invoke(app, ["fixtures", "--league", "epl", "--demo"])

    assert result.exit_code == 0
    assert "Arsenal vs Tottenham Hotspur" in result.stdout
    assert "Manchester City vs Liverpool" in result.stdout


def test_fixtures_sync_command_persists_and_lists_data(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "demo-key")
    clear_settings_cache()

    def fake_fetch(self, **kwargs):
        league_code = kwargs["league_code"]
        return FixtureBatch(
            fixtures=sample_fixtures(league_code),
            requests_made=1,
            quota=ApiQuota(requests_remaining=7400, minute_remaining=58),
        )

    monkeypatch.setattr(ApiFootballClient, "fetch_upcoming_fixtures", fake_fetch)

    sync_result = runner.invoke(app, ["fixtures-sync", "--league", "epl", "--days", "7"])
    list_result = runner.invoke(app, ["fixtures", "--league", "epl", "--next", "7"])
    doctor_result = runner.invoke(app, ["doctor", "--format", "json"])
    payload = json.loads(doctor_result.stdout)

    assert sync_result.exit_code == 0
    assert "Synced 2 fixtures across 1 competition(s)." in sync_result.stdout
    assert list_result.exit_code == 0
    assert "Arsenal vs Tottenham Hotspur" in list_result.stdout
    assert payload["latest_sync"]["status"] == "success"
    assert payload["latest_sync"]["fixtures_written"] == 2


def test_fixtures_sync_command_passes_past_days_to_provider(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "demo-key")
    clear_settings_cache()
    calls: list[dict[str, object]] = []

    def fake_fetch(self, **kwargs):
        calls.append(kwargs)
        league_code = kwargs["league_code"]
        return FixtureBatch(
            fixtures=sample_fixtures(league_code),
            requests_made=1,
            quota=ApiQuota(requests_remaining=7400, minute_remaining=58),
        )

    monkeypatch.setattr(ApiFootballClient, "fetch_upcoming_fixtures", fake_fetch)

    result = runner.invoke(
        app,
        ["fixtures-sync", "--league", "epl", "--days", "7", "--past-days", "3"],
    )

    assert result.exit_code == 0
    assert calls
    assert (calls[0]["date_to"] - calls[0]["date_from"]).days == 10


def test_fixtures_sync_command_fails_cleanly_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "")
    clear_settings_cache()
    result = runner.invoke(app, ["fixtures-sync", "--league", "epl", "--days", "7"])
    doctor_result = runner.invoke(app, ["doctor", "--format", "json"])
    payload = json.loads(doctor_result.stdout)

    assert result.exit_code == 2
    assert "NUTMEG_API_FOOTBALL_KEY is not configured" in result.stdout
    assert payload["latest_sync"]["status"] == "failed"


def test_fixture_snapshot_command_returns_json(monkeypatch) -> None:
    runner.invoke(app, ["seed-demo", "--league", "epl"])
    _stub_context_providers(monkeypatch)

    def fake_fetch(self, *, fixture, recent_matches=5):
        assert fixture.fixture_id == "epl-001"
        assert recent_matches == 5
        return SoccerDataFixtureBundle(
            league_code="epl",
            season=fixture.season,
            home=TeamEnrichment(
                canonical_name="Arsenal",
                source_names={"fbref": "Arsenal", "understat": "Arsenal"},
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
                canonical_name="Tottenham Hotspur",
                source_names={"fbref": "Tottenham Hotspur", "understat": "Tottenham"},
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

    monkeypatch.setattr(SoccerDataClient, "fetch_fixture_enrichment", fake_fetch)
    monkeypatch.setattr(
        TransfermarktDataset,
        "fetch_team_market_value",
        lambda self, league_code, team_name: TeamMarketValue(
            source="transfermarkt-datasets",
            total_market_value_eur=800000000 if team_name == "Arsenal" else 650000000,
            top_players=[("Bukayo Saka", 140000000)],
        ),
    )
    monkeypatch.setattr(
        TransfermarktDataset,
        "build_probable_lineup",
        lambda self, *, league_code, team_name, unavailable_players, recent_games=5: TeamLineup(
            status="probable",
            source="transfermarkt-datasets",
            formation="4-3-3",
            players=[
                LineupPlayer(
                    player_name="Martin Odegaard" if team_name == "Arsenal" else "Son Heung-min",
                    position="M" if team_name == "Arsenal" else "F",
                    shirt_number="8" if team_name == "Arsenal" else "7",
                    role="starter",
                    captain=True,
                )
            ],
        ),
    )
    monkeypatch.setattr(
        ApiFootballClient,
        "fetch_fixture_injuries",
        lambda self, fixture_id: {
            42: [
                InjuryStatus(
                    player_name="Bukayo Saka",
                    status="Injured",
                    reason="Hamstring",
                    expected_return=None,
                    source="api-football",
                )
            ]
        },
    )
    monkeypatch.setattr(ApiFootballClient, "fetch_fixture_lineups", lambda self, fixture_id: {})

    result = runner.invoke(app, ["fixture-snapshot", "--fixture-id", "epl-001", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["fixture"]["fixture_id"] == "epl-001"
    assert payload["home"]["source_names"]["understat"] == "Arsenal"
    assert payload["away"]["source_names"]["understat"] == "Tottenham"
    assert payload["home"]["market_value"]["total_market_value_eur"] == 800000000
    assert payload["home"]["injuries"][0]["player_name"] == "Bukayo Saka"
    assert payload["home"]["lineup"]["status"] == "probable"
    assert payload["deferred_sections"] == []


def test_fixture_snapshot_command_keeps_json_stdout_clean(monkeypatch) -> None:
    runner.invoke(app, ["seed-demo", "--league", "epl"])
    _stub_context_providers(monkeypatch)

    def noisy_fetch(self, *, fixture, recent_matches=5):
        print("provider-noise-on-stdout")
        return SoccerDataFixtureBundle(
            league_code="epl",
            season=fixture.season,
            home=TeamEnrichment(
                canonical_name="Arsenal",
                source_names={"fbref": "Arsenal", "understat": "Arsenal"},
                season_metrics=None,
                recent_form=None,
                shot_summary=None,
                market_value=None,
                injuries=[],
                lineup=None,
            ),
            away=TeamEnrichment(
                canonical_name="Tottenham Hotspur",
                source_names={"fbref": "Tottenham Hotspur", "understat": "Tottenham"},
                season_metrics=None,
                recent_form=None,
                shot_summary=None,
                market_value=None,
                injuries=[],
                lineup=None,
            ),
        )

    monkeypatch.setattr(SoccerDataClient, "fetch_fixture_enrichment", noisy_fetch)
    monkeypatch.setattr(
        TransfermarktDataset,
        "fetch_team_market_value",
        lambda self, league_code, team_name: None,
    )
    monkeypatch.setattr(
        TransfermarktDataset,
        "build_probable_lineup",
        lambda self, *, league_code, team_name, unavailable_players, recent_games=5: None,
    )
    monkeypatch.setattr(ApiFootballClient, "fetch_fixture_injuries", lambda self, fixture_id: {})
    monkeypatch.setattr(ApiFootballClient, "fetch_fixture_lineups", lambda self, fixture_id: {})

    result = runner.invoke(app, ["fixture-snapshot", "--fixture-id", "epl-001", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["fixture"]["fixture_id"] == "epl-001"
    assert "provider-noise-on-stdout" not in result.stdout
    assert "provider-noise-on-stdout" in result.stderr


def test_fixture_snapshot_command_suppresses_root_info_logs_in_json_mode(
    monkeypatch,
) -> None:
    runner.invoke(app, ["seed-demo", "--league", "epl"])
    _stub_context_providers(monkeypatch)

    def noisy_fetch(self, *, fixture, recent_matches=5):
        logging.getLogger("root").info("provider-root-noise")
        return SoccerDataFixtureBundle(
            league_code="epl",
            season=fixture.season,
            home=TeamEnrichment(
                canonical_name="Arsenal",
                source_names={"fbref": "Arsenal", "understat": "Arsenal"},
                season_metrics=None,
                recent_form=None,
                shot_summary=None,
                market_value=None,
                injuries=[],
                lineup=None,
            ),
            away=TeamEnrichment(
                canonical_name="Tottenham Hotspur",
                source_names={"fbref": "Tottenham Hotspur", "understat": "Tottenham"},
                season_metrics=None,
                recent_form=None,
                shot_summary=None,
                market_value=None,
                injuries=[],
                lineup=None,
            ),
        )

    monkeypatch.setattr(SoccerDataClient, "fetch_fixture_enrichment", noisy_fetch)
    monkeypatch.setattr(
        TransfermarktDataset,
        "fetch_team_market_value",
        lambda self, league_code, team_name: None,
    )
    monkeypatch.setattr(
        TransfermarktDataset,
        "build_probable_lineup",
        lambda self, *, league_code, team_name, unavailable_players, recent_games=5: None,
    )
    monkeypatch.setattr(ApiFootballClient, "fetch_fixture_injuries", lambda self, fixture_id: {})
    monkeypatch.setattr(ApiFootballClient, "fetch_fixture_lineups", lambda self, fixture_id: {})

    root_logger = logging.getLogger("root")
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level
    root_logger.handlers = [logging.StreamHandler(sys.stdout)]
    root_logger.setLevel(logging.INFO)
    try:
        result = runner.invoke(
            app,
            ["fixture-snapshot", "--fixture-id", "epl-001", "--format", "json"],
        )
    finally:
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)

    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["fixture"]["fixture_id"] == "epl-001"
    assert "provider-root-noise" not in result.stdout


def test_fixture_snapshot_command_fails_for_unknown_fixture(monkeypatch) -> None:
    monkeypatch.setattr(
        SoccerDataClient,
        "fetch_fixture_enrichment",
        lambda self, *, fixture, recent_matches=5: None,
    )

    result = runner.invoke(app, ["fixture-snapshot", "--fixture-id", "missing-001"])

    assert result.exit_code == 2
    assert "missing-001" in result.stdout


def test_reference_refresh_command_reports_materialized_counts(monkeypatch) -> None:
    from nutmeg.services.materialization import MaterializationResult

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_materialization_service",
        lambda: (
            type(
                "FakeMaterializationService",
                (),
                {
                    "refresh_snapshot_support_data": lambda self, league_code, season: (
                        MaterializationResult(
                            league_code=league_code,
                            season=season,
                            transfermarkt_rows=12,
                            soccerdata_rows=8,
                        )
                    )
                },
            )(),
            None,
        ),
    )

    result = runner.invoke(
        app,
        ["reference-refresh", "--league", "epl", "--season", "2025"],
    )

    assert result.exit_code == 0
    assert "transfermarkt_rows=12" in result.stdout
    assert "soccerdata_rows=8" in result.stdout


def test_fixture_snapshot_command_returns_richer_snapshot_sections(monkeypatch) -> None:
    class FakeSnapshotService:
        def build_snapshot(self, fixture_id: str, *, recent_matches: int = 5):
            fixture = sample_fixtures("epl")[0]
            assert fixture_id == "epl-001"
            assert recent_matches == 5
            return FixtureSnapshot(
                fixture=fixture,
                home=TeamEnrichment(
                    canonical_name="Arsenal",
                    source_names={"fbref": "Arsenal", "understat": "Arsenal"},
                    season_metrics=None,
                    recent_form=None,
                    shot_summary=None,
                    market_value=TeamMarketValue(
                        source="transfermarkt-datasets",
                        total_market_value_eur=800000000,
                        top_players=[("Bukayo Saka", 140000000)],
                    ),
                    injuries=[],
                    lineup=None,
                    availability=AvailabilityContext(
                        injuries=[
                            AvailabilityRecord(
                                player_name="Bukayo Saka",
                                status="Injured",
                                reason="Hamstring",
                                expected_return="2026-04-28",
                                source="api-football",
                            )
                        ],
                        suspensions=[],
                        returning_players=[
                            AvailabilityRecord(
                                player_name="Bukayo Saka",
                                status="Returning Soon",
                                reason="Hamstring",
                                expected_return="2026-04-28",
                                source="api-football",
                            )
                        ],
                        expected_absences_summary="1 injury",
                        bench_depth=BenchDepthContext(
                            bench_market_value_eur=210000000,
                            available_players=15,
                            label="strong",
                            source="transfermarkt-datasets",
                        ),
                    ),
                ),
                away=TeamEnrichment(
                    canonical_name="Tottenham Hotspur",
                    source_names={"fbref": "Tottenham Hotspur", "understat": "Tottenham"},
                    season_metrics=None,
                    recent_form=None,
                    shot_summary=None,
                    market_value=None,
                    injuries=[],
                    lineup=None,
                    availability=AvailabilityContext(
                        injuries=[],
                        suspensions=[
                            AvailabilityRecord(
                                player_name="Cristian Romero",
                                status="Suspended",
                                reason="Cards",
                                expected_return="2026-04-30",
                                source="api-football",
                            )
                        ],
                        returning_players=[],
                        expected_absences_summary="1 suspension",
                        bench_depth=None,
                    ),
                ),
                deferred_sections=[],
                generated_at=fixture.kickoff_at,
                environment=EnvironmentContext(
                    venue_name="Emirates Stadium",
                    referee="Michael Oliver",
                    kickoff_local_time=fixture.kickoff_at,
                    weather=WeatherContext(
                        forecast_at=fixture.kickoff_at,
                        temperature_c=14.2,
                        precipitation_probability=20,
                        wind_speed_kph=12.8,
                        weather_code=3,
                        source="open-meteo",
                    ),
                    home_rest_days=None,
                    away_rest_days=None,
                    away_travel=TravelContext(
                        distance_km=10.4,
                        bucket="short-haul",
                        source="open-meteo",
                    ),
                    source_names={
                        "fixture": "api-football",
                        "weather": "open-meteo",
                        "travel": "open-meteo",
                    },
                ),
                matchup=MatchupTrendContext(
                    head_to_head=HeadToHeadSummary(
                        matches=5,
                        home_wins=3,
                        draws=1,
                        away_wins=1,
                        source="api-football",
                    ),
                    home_split=TeamSplitSummary(
                        home_points_per_match=2.2,
                        away_points_per_match=1.4,
                        home_goals_for_per_match=2.1,
                        away_goals_for_per_match=1.5,
                        source="api-football",
                    ),
                    away_split=TeamSplitSummary(
                        home_points_per_match=1.9,
                        away_points_per_match=1.3,
                        home_goals_for_per_match=2.0,
                        away_goals_for_per_match=1.4,
                        source="api-football",
                    ),
                    home_trend=TeamTrendSummary(
                        sample_size=5,
                        goals_for_per_match=1.8,
                        xg_for_per_match=1.68,
                        goals_against_per_match=0.8,
                        xg_against_per_match=0.94,
                        set_piece_shot_share=0.24,
                        source="soccerdata",
                    ),
                    away_trend=TeamTrendSummary(
                        sample_size=5,
                        goals_for_per_match=1.4,
                        xg_for_per_match=1.42,
                        goals_against_per_match=1.2,
                        xg_against_per_match=1.28,
                        set_piece_shot_share=0.33,
                        source="soccerdata",
                    ),
                ),
            )

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_snapshot_service",
        lambda: (
            FakeSnapshotService(),
            type("FakeSession", (), {"close": lambda self: None})(),
        ),
    )

    result = runner.invoke(
        app,
        ["fixture-snapshot", "--fixture-id", "epl-001", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["environment"]["referee"] == "Michael Oliver"
    assert payload["environment"]["weather"]["source"] == "open-meteo"
    assert payload["home"]["availability"]["expected_absences_summary"] == "1 injury"
    assert payload["home"]["availability"]["bench_depth"]["label"] == "strong"
    assert payload["matchup"]["head_to_head"]["matches"] == 5
    assert payload["matchup"]["home_trend"]["set_piece_shot_share"] == 0.24


def test_fixture_snapshot_command_renders_richer_text_sections(monkeypatch) -> None:
    fixture = sample_fixtures("epl")[0]
    snapshot = FixtureSnapshot(
        fixture=fixture,
        home=TeamEnrichment(
            canonical_name="Arsenal",
            source_names={"fbref": "Arsenal", "understat": "Arsenal"},
            season_metrics=None,
            recent_form=None,
            shot_summary=None,
            market_value=None,
            injuries=[],
            lineup=None,
            availability=AvailabilityContext(
                injuries=[
                    AvailabilityRecord(
                        player_name="Bukayo Saka",
                        status="Injured",
                        reason="Hamstring",
                        expected_return="2026-04-28",
                        source="api-football",
                    )
                ],
                suspensions=[],
                returning_players=[],
                expected_absences_summary="1 injury",
                bench_depth=BenchDepthContext(
                    bench_market_value_eur=210000000,
                    available_players=15,
                    label="strong",
                    source="transfermarkt-datasets",
                ),
            ),
        ),
        away=TeamEnrichment(
            canonical_name="Tottenham Hotspur",
            source_names={"fbref": "Tottenham Hotspur", "understat": "Tottenham"},
            season_metrics=None,
            recent_form=None,
            shot_summary=None,
            market_value=None,
            injuries=[],
            lineup=None,
            availability=None,
        ),
        deferred_sections=[],
        generated_at=fixture.kickoff_at,
        environment=EnvironmentContext(
            venue_name="Emirates Stadium",
            referee="Michael Oliver",
            kickoff_local_time=fixture.kickoff_at,
            weather=WeatherContext(
                forecast_at=fixture.kickoff_at,
                temperature_c=14.2,
                precipitation_probability=20,
                wind_speed_kph=12.8,
                weather_code=3,
                source="open-meteo",
            ),
            home_rest_days=None,
            away_rest_days=None,
            away_travel=TravelContext(
                distance_km=10.4,
                bucket="short-haul",
                source="open-meteo",
            ),
            source_names={},
        ),
        matchup=MatchupTrendContext(
            head_to_head=HeadToHeadSummary(
                matches=5,
                home_wins=3,
                draws=1,
                away_wins=1,
                source="api-football",
            ),
            home_split=None,
            away_split=None,
            home_trend=TeamTrendSummary(
                sample_size=5,
                goals_for_per_match=1.8,
                xg_for_per_match=1.68,
                goals_against_per_match=0.8,
                xg_against_per_match=0.94,
                set_piece_shot_share=0.24,
                source="soccerdata",
            ),
            away_trend=None,
        ),
    )

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_snapshot_service",
        lambda: (
            type(
                "FakeSnapshotService",
                (),
                {"build_snapshot": lambda self, fixture_id, recent_matches=5: snapshot},
            )(),
            type("FakeSession", (), {"close": lambda self: None})(),
        ),
    )

    result = runner.invoke(app, ["fixture-snapshot", "--fixture-id", "epl-001"])

    assert result.exit_code == 0
    assert "environment venue=Emirates Stadium referee=Michael Oliver" in result.stdout
    assert "availability injuries=1 suspensions=0 returning=0 summary=1 injury" in result.stdout
    assert "bench depth label=strong available=15" in result.stdout
    assert "matchup h2h=5 home_trend=1.80/1.68" in result.stdout


def test_odds_snapshot_command_returns_json(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.odds import (
        BookmakerQuote,
        MarketOddsSnapshot,
        OddsProviderSnapshot,
        OddsSnapshot,
        OutcomeOddsSnapshot,
    )

    fixture = sample_fixtures("epl")[0]
    snapshot = OddsSnapshot(
        fixture=fixture,
        provider=OddsProviderSnapshot(
            name="api-football",
            updated_at=datetime(2026, 4, 24, 6, 16, 30, tzinfo=UTC),
            bookmaker_count=2,
        ),
        markets={
            "match_winner": MarketOddsSnapshot(
                market_key="match_winner",
                market_name="Match Winner",
                status="available",
                line=None,
                source_market_ids=[1],
                outcomes=[
                    OutcomeOddsSnapshot(
                        outcome_key="home",
                        outcome_name="Home",
                        bookmaker_quotes=[
                            BookmakerQuote(
                                bookmaker_id=1,
                                bookmaker_name="10Bet",
                                market_id=1,
                                market_name="Match Winner",
                                selection_value="Home",
                                decimal_odds=1.48,
                                source="api-football",
                            )
                        ],
                        best_odds=1.48,
                        average_odds=1.48,
                        fair_probability=0.63,
                        fair_odds=1.59,
                        bookmaker_count=1,
                    )
                ],
            )
        },
        deferred_sections=[],
    )

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_odds_service",
        lambda: (
            type(
                "FakeOddsService",
                (),
                {"build_snapshot": lambda self, fixture_id: snapshot},
            )(),
            type("FakeSession", (), {"close": lambda self: None})(),
        ),
        raising=False,
    )

    result = runner.invoke(
        app,
        ["odds-snapshot", "--fixture-id", fixture.fixture_id, "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["provider"]["name"] == "api-football"
    assert (
        payload["markets"]["match_winner"]["outcomes"][0]["bookmaker_quotes"][0]["bookmaker_name"]
        == "10Bet"
    )
    assert payload["markets"]["match_winner"]["outcomes"][0]["fair_probability"] == 0.63


def test_odds_snapshot_command_fails_cleanly_for_missing_fixture(monkeypatch) -> None:
    from nutmeg.services.odds import OddsFixtureNotFoundError

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_odds_service",
        lambda: (
            type(
                "FakeOddsService",
                (),
                {
                    "build_snapshot": lambda self, fixture_id: (_ for _ in ()).throw(
                        OddsFixtureNotFoundError(
                            f"Fixture `{fixture_id}` was not found in the local cache."
                        )
                    )
                },
            )(),
            type("FakeSession", (), {"close": lambda self: None})(),
        ),
        raising=False,
    )

    result = runner.invoke(app, ["odds-snapshot", "--fixture-id", "missing-001"])

    assert result.exit_code == 2
    assert "missing-001" in result.stdout


def test_odds_snapshot_command_renders_text(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.odds import (
        BookmakerQuote,
        HistoricalMarketPoint,
        HistoricalMarketSummary,
        MarketOddsSnapshot,
        OddsProviderSnapshot,
        OddsSnapshot,
        OutcomeOddsSnapshot,
    )

    fixture = sample_fixtures("epl")[0]
    snapshot = OddsSnapshot(
        fixture=fixture,
        provider=OddsProviderSnapshot(
            name="api-football",
            updated_at=datetime(2026, 4, 24, 6, 16, 30, tzinfo=UTC),
            bookmaker_count=2,
        ),
        markets={
            "match_winner": MarketOddsSnapshot(
                market_key="match_winner",
                market_name="Match Winner",
                status="available",
                line=None,
                source_market_ids=[1],
                outcomes=[
                    OutcomeOddsSnapshot(
                        outcome_key="home",
                        outcome_name="Home",
                        bookmaker_quotes=[
                            BookmakerQuote(
                                bookmaker_id=1,
                                bookmaker_name="10Bet",
                                market_id=1,
                                market_name="Match Winner",
                                selection_value="Home",
                                decimal_odds=1.48,
                                source="api-football",
                            )
                        ],
                        best_odds=1.48,
                        average_odds=1.48,
                        fair_probability=0.63,
                        fair_odds=1.59,
                        bookmaker_count=1,
                    )
                ],
            )
        },
        deferred_sections=[],
        history={
            "match_winner": HistoricalMarketSummary(
                market_key="match_winner",
                line=None,
                points=[
                    HistoricalMarketPoint(
                        captured_at=datetime(2026, 4, 24, 5, 16, 30, tzinfo=UTC),
                        provider="api-football",
                        market_key="match_winner",
                        line=None,
                        outcome_probabilities={"home": 0.63},
                        outcome_fair_odds={"home": 1.59},
                        outcome_best_odds={"home": 1.48},
                        bookmaker_count=1,
                    )
                ],
                drift_vs_current={"home": 0.0},
                movement="flat",
                movement_span=0.0,
            )
        },
    )

    monkeypatch.setattr(
        "nutmeg.interfaces.cli.build_odds_service",
        lambda: (
            type(
                "FakeOddsService",
                (),
                {"build_snapshot": lambda self, fixture_id: snapshot},
            )(),
            type("FakeSession", (), {"close": lambda self: None})(),
        ),
        raising=False,
    )

    result = runner.invoke(app, ["odds-snapshot", "--fixture-id", fixture.fixture_id])

    assert result.exit_code == 0
    assert (
        "provider name=api-football updated=2026-04-24T06:16:30+00:00 bookmakers=2" in result.stdout
    )
    assert "match_winner status=available source_ids=[1]" in result.stdout
    assert "home best=1.48 avg=1.48 fair_prob=0.6300 fair_odds=1.590 books=1" in result.stdout
    assert "history points=1 movement=flat span=0.0 drift={'home': 0.0}" in result.stdout


def test_odds_snapshot_command_fails_cleanly_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "")
    clear_settings_cache()
    runner.invoke(app, ["seed-demo", "--league", "epl"])

    result = runner.invoke(app, ["odds-snapshot", "--fixture-id", "epl-001"])

    assert result.exit_code == 2
    assert "NUTMEG_API_FOOTBALL_KEY is not configured" in result.stdout


def test_analyze_match_command_returns_json(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]

    class StubAnalysisService:
        def analyze_match(self, fixture_id: str, *, query: str):
            assert fixture_id == fixture.fixture_id
            return FixtureAnalysisResult(
                fixture=fixture,
                intent=QueryIntent.DECISIONAL,
                query=query,
                evidence=AnalysisEvidenceSummary(
                    tactical_summary=["Arsenal can pin Spurs with the wider front three."],
                    snapshot_summary=["Arsenal squad edge"],
                    odds_summary=["Market still prices Arsenal as favorite"],
                    market_shape_summary=["Market shape points to an open game."],
                    caveats=[],
                ),
                judgment=AnalysisJudgment(
                    verdict="Back Arsenal pre-match.",
                    core_reasons=[
                        "Squad availability edge",
                        "Market still supports home side",
                    ],
                    counterargument="Tottenham transition threat can punish a high line.",
                    confidence="medium",
                ),
                conflict_state="aligned",
                generated_at=fixture.kickoff_at,
            )

    monkeypatch.setattr(
        cli_module,
        "build_analysis_service",
        lambda: (StubAnalysisService(), None),
    )

    result = runner.invoke(
        app,
        [
            "analyze-match",
            "--fixture-id",
            fixture.fixture_id,
            "--query",
            "Should I back Arsenal?",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["intent"] == "decisional"
    assert payload["judgment"]["confidence"] == "medium"
    assert payload["evidence"]["snapshot_summary"][0] == "Arsenal squad edge"


def test_analyze_match_command_fails_cleanly(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module
    from nutmeg.services.analysis import InsufficientEvidenceError

    class StubAnalysisService:
        def analyze_match(self, fixture_id: str, *, query: str):
            raise InsufficientEvidenceError("Not enough evidence for a direct call.")

    monkeypatch.setattr(
        cli_module,
        "build_analysis_service",
        lambda: (StubAnalysisService(), None),
    )

    result = runner.invoke(
        app,
        ["analyze-match", "--fixture-id", "epl-001", "--query", "Show me context"],
    )

    assert result.exit_code == 2
    assert "Not enough evidence for a direct call." in result.stdout


def test_analyze_match_command_text_includes_market_shape(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]

    class StubAnalysisService:
        def analyze_match(self, fixture_id: str, *, query: str):
            return FixtureAnalysisResult(
                fixture=fixture,
                intent=QueryIntent.DECISIONAL,
                query=query,
                evidence=AnalysisEvidenceSummary(
                    tactical_summary=["Arsenal press can stretch Spurs."],
                    snapshot_summary=["Arsenal squad edge"],
                    odds_summary=["Market still prices Arsenal as favorite"],
                    market_shape_summary=["Market shape points to an open game."],
                    caveats=["Market shape is partial, so confidence is capped."],
                ),
                judgment=AnalysisJudgment(
                    verdict="Back Arsenal pre-match.",
                    core_reasons=["Arsenal press can stretch Spurs."],
                    counterargument="Spurs can still hit transition windows.",
                    confidence="medium",
                ),
                conflict_state="aligned",
                generated_at=fixture.kickoff_at,
            )

    monkeypatch.setattr(
        cli_module,
        "build_analysis_service",
        lambda: (StubAnalysisService(), None),
    )

    result = runner.invoke(
        app,
        ["analyze-match", "--fixture-id", fixture.fixture_id, "--query", "Should I back Arsenal?"],
    )

    assert result.exit_code == 0
    assert "Market shape points to an open game." in result.stdout
    assert "Conflict state: aligned" in result.stdout


def test_analyze_match_command_json_preserves_handicap_pressure_contract(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]
    pressure = (
        "Asian handicap pressure reaches 2.0: the favorite is being priced "
        "to win by margin, not just edge the match."
    )

    class StubAnalysisService:
        def analyze_match(self, fixture_id: str, *, query: str):
            assert fixture_id == fixture.fixture_id
            return FixtureAnalysisResult(
                fixture=fixture,
                intent=QueryIntent.DECISIONAL,
                query=query,
                evidence=AnalysisEvidenceSummary(
                    tactical_summary=["Arsenal press can stretch Spurs."],
                    snapshot_summary=["Arsenal squad edge"],
                    odds_summary=["Market still prices Arsenal as favorite"],
                    market_shape_summary=[pressure],
                    caveats=[],
                ),
                judgment=AnalysisJudgment(
                    verdict="Back Arsenal pre-match.",
                    core_reasons=["Market pressure is stronger than a result-only lean."],
                    counterargument="Spurs can still hit transition windows.",
                    confidence="medium",
                ),
                conflict_state="aligned",
                generated_at=fixture.kickoff_at,
            )

    monkeypatch.setattr(
        cli_module,
        "build_analysis_service",
        lambda: (StubAnalysisService(), None),
    )

    result = runner.invoke(
        app,
        [
            "analyze-match",
            "--fixture-id",
            fixture.fixture_id,
            "--query",
            "Should I back Arsenal?",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["evidence"]["market_shape_summary"] == [pressure]
    assert "Asian handicap pressure" in result.stdout


def test_analyze_match_command_json_preserves_market_intelligence_fields(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]
    movement = "Market movement is toward home: drift +7.0% over a 5.0% span."
    disagreement = "Bookmaker disagreement is elevated on home pricing."

    class StubAnalysisService:
        def analyze_match(self, fixture_id: str, *, query: str):
            return FixtureAnalysisResult(
                fixture=fixture,
                intent=QueryIntent.DECISIONAL,
                query=query,
                evidence=AnalysisEvidenceSummary(
                    tactical_summary=["Arsenal press can stretch Spurs."],
                    snapshot_summary=["Arsenal squad edge"],
                    odds_summary=["Market still prices Arsenal as favorite", movement],
                    market_shape_summary=["Market shape points to an open game."],
                    caveats=[disagreement],
                ),
                judgment=AnalysisJudgment(
                    verdict="Back Arsenal pre-match.",
                    core_reasons=["Market still prices Arsenal as favorite"],
                    counterargument="Spurs can still hit transition windows.",
                    confidence="medium",
                ),
                conflict_state="aligned",
                generated_at=fixture.kickoff_at,
            )

    monkeypatch.setattr(
        cli_module,
        "build_analysis_service",
        lambda: (StubAnalysisService(), None),
    )

    result = runner.invoke(
        app,
        [
            "analyze-match",
            "--fixture-id",
            fixture.fixture_id,
            "--query",
            "Should I back Arsenal?",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert movement in payload["evidence"]["odds_summary"]
    assert disagreement in payload["evidence"]["caveats"]
    assert "market_intelligence" not in payload["evidence"]


def test_analyze_match_command_text_includes_market_intelligence(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]
    movement = "Market movement is toward home: drift +7.0% over a 5.0% span."
    disagreement = "Bookmaker disagreement is elevated on home pricing."

    class StubAnalysisService:
        def analyze_match(self, fixture_id: str, *, query: str):
            return FixtureAnalysisResult(
                fixture=fixture,
                intent=QueryIntent.DECISIONAL,
                query=query,
                evidence=AnalysisEvidenceSummary(
                    tactical_summary=["Arsenal press can stretch Spurs."],
                    snapshot_summary=["Arsenal squad edge"],
                    odds_summary=["Market still prices Arsenal as favorite", movement],
                    market_shape_summary=[],
                    caveats=[disagreement],
                ),
                judgment=AnalysisJudgment(
                    verdict="Back Arsenal pre-match.",
                    core_reasons=["Market still prices Arsenal as favorite"],
                    counterargument="Spurs can still hit transition windows.",
                    confidence="medium",
                ),
                conflict_state="aligned",
                generated_at=fixture.kickoff_at,
            )

    monkeypatch.setattr(
        cli_module,
        "build_analysis_service",
        lambda: (StubAnalysisService(), None),
    )

    result = runner.invoke(
        app,
        ["analyze-match", "--fixture-id", fixture.fixture_id, "--query", "Should I back Arsenal?"],
    )

    assert result.exit_code == 0
    assert movement in result.stdout
    assert disagreement in result.stdout


def test_agent_analyze_match_command_returns_json(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="succeeded",
                nodes=["classify_intent", "analyze_match", "synthesize_result"],
                analysis=FixtureAnalysisResult(
                    fixture=fixture,
                    intent=QueryIntent.DECISIONAL,
                    query=query,
                    evidence=AnalysisEvidenceSummary(
                        tactical_summary=["Arsenal can press high."],
                        snapshot_summary=["Arsenal squad edge"],
                        odds_summary=["Market fair view leans Arsenal."],
                        market_shape_summary=[],
                        caveats=[],
                    ),
                    judgment=AnalysisJudgment(
                        verdict="Lean Arsenal pre-match.",
                        core_reasons=["Arsenal can press high."],
                        counterargument="Spurs transition threat remains live.",
                        confidence="medium",
                    ),
                    conflict_state="aligned",
                    generated_at=fixture.kickoff_at,
                ),
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    result = runner.invoke(
        app,
        [
            "agent-analyze-match",
            "--fixture-id",
            fixture.fixture_id,
            "--query",
            "Should I back Arsenal?",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["status"] == "succeeded"
    assert payload["nodes"] == ["classify_intent", "analyze_match", "synthesize_result"]
    assert payload["analysis"]["judgment"]["verdict"] == "Lean Arsenal pre-match."


def test_agent_analyze_match_command_text_and_failure(monkeypatch) -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.interfaces import cli as cli_module

    class StubWorkflow:
        def __init__(self, *, status: str) -> None:
            self.status = status

        def run(self, *, fixture_id: str, query: str):
            if self.status == "failed":
                return MatchAnalysisAgentResult(
                    fixture_id=fixture_id,
                    query=query,
                    status="failed",
                    nodes=["classify_intent", "analyze_match"],
                    error="Not enough evidence for a direct call.",
                )
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="succeeded",
                nodes=["classify_intent", "analyze_match", "synthesize_result"],
                error=None,
            )

    monkeypatch.setattr(
        cli_module,
        "build_agent_workflow",
        lambda: (StubWorkflow(status="ok"), None),
    )
    ok = runner.invoke(
        app,
        ["agent-analyze-match", "--fixture-id", "epl-001", "--query", "Should I back Arsenal?"],
    )

    monkeypatch.setattr(
        cli_module,
        "build_agent_workflow",
        lambda: (StubWorkflow(status="failed"), None),
    )
    failed = runner.invoke(
        app,
        ["agent-analyze-match", "--fixture-id", "epl-001", "--query", "Show me context"],
    )

    assert ok.exit_code == 0
    assert "Agent status: succeeded" in ok.stdout
    assert "classify_intent -> analyze_match -> synthesize_result" in ok.stdout
    assert failed.exit_code == 2
    assert "Not enough evidence for a direct call." in failed.stdout


def test_agent_analyze_match_command_json_includes_generated_synthesis(monkeypatch) -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.interfaces import cli as cli_module

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="succeeded",
                nodes=["classify_intent", "analyze_match", "synthesize_result", "guard_synthesis"],
                generated_synthesis="Lean Arsenal pre-match. Confidence: medium.",
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    result = runner.invoke(
        app,
        [
            "agent-analyze-match",
            "--fixture-id",
            "epl-001",
            "--query",
            "Should I back Arsenal?",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["generated_synthesis"] == "Lean Arsenal pre-match. Confidence: medium."


def test_agent_analyze_match_command_text_renders_generated_synthesis(monkeypatch) -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.interfaces import cli as cli_module

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="succeeded",
                nodes=["classify_intent", "analyze_match", "synthesize_result", "guard_synthesis"],
                generated_synthesis="Lean Arsenal pre-match. Confidence: medium.",
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    result = runner.invoke(
        app,
        ["agent-analyze-match", "--fixture-id", "epl-001", "--query", "Should I back Arsenal?"],
    )

    assert result.exit_code == 0
    assert "Generated synthesis:" in result.stdout
    assert "Lean Arsenal pre-match. Confidence: medium." in result.stdout


def test_doctor_json_reports_agent_synthesis_configuration(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_AGENT_SYNTHESIS_ENABLED", "true")
    monkeypatch.setenv("NUTMEG_PORTKEY_API_KEY", "demo-secret")
    monkeypatch.setenv("NUTMEG_ANTHROPIC_MODEL", "claude-test")
    clear_settings_cache()

    result = runner.invoke(app, ["doctor", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["providers"]["agent_synthesis_enabled"] is True
    assert payload["providers"]["agent_synthesis_configured"] is True
    assert payload["providers"]["agent_synthesis_model"] == "claude-test"
    assert "demo-secret" not in result.stdout


def test_agent_status_json_reports_executor_and_provider_health(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_ODDS_PROVIDER", "the-odds-api")
    monkeypatch.setenv("NUTMEG_THE_ODDS_API_KEY", "odds-secret")
    clear_settings_cache()

    result = runner.invoke(app, ["agent-status", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["agent"]["executor"] in {"langgraph", "deterministic"}
    assert "langgraph_available" in payload["agent"]
    assert payload["odds_provider"]["name"] == "the-odds-api"
    assert payload["odds_provider"]["configured"] is True
    assert payload["odds_provider"]["health_metrics_available"] is True
    assert "odds-secret" not in result.stdout


def test_agent_status_reports_synthesis_configuration_without_key(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_AGENT_SYNTHESIS_ENABLED", "true")
    monkeypatch.setenv("NUTMEG_PORTKEY_API_KEY", "portkey-secret")
    monkeypatch.setenv("NUTMEG_ANTHROPIC_MODEL", "claude-test")
    clear_settings_cache()

    json_result = runner.invoke(app, ["agent-status", "--format", "json"])
    text_result = runner.invoke(app, ["agent-status"])
    payload = json.loads(json_result.stdout)

    assert json_result.exit_code == 0
    assert payload["synthesis"]["enabled"] is True
    assert payload["synthesis"]["configured"] is True
    assert payload["synthesis"]["model"] == "claude-test"
    assert "portkey-secret" not in json_result.stdout
    assert text_result.exit_code == 0
    assert "synthesis enabled=yes configured=yes model=claude-test" in text_result.stdout
    assert "portkey-secret" not in text_result.stdout


def test_match_brief_command_json_returns_operator_payload(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="succeeded",
                nodes=["classify_intent", "analyze_match", "synthesize_result"],
                executor="deterministic",
                generated_synthesis="Lean Arsenal pre-match. Confidence: medium.",
                analysis=FixtureAnalysisResult(
                    fixture=fixture,
                    intent=QueryIntent.DECISIONAL,
                    query=query,
                    evidence=AnalysisEvidenceSummary(
                        tactical_summary=["Arsenal can press high."],
                        snapshot_summary=["Arsenal squad edge."],
                        odds_summary=["Market fair view leans Arsenal."],
                        market_shape_summary=["Market shape is open."],
                        caveats=["Tottenham transition threat remains live."],
                    ),
                    judgment=AnalysisJudgment(
                        verdict="Lean Arsenal pre-match.",
                        core_reasons=["Pressing edge", "Market alignment"],
                        counterargument="Derby variance remains elevated.",
                        confidence="medium",
                    ),
                    conflict_state="aligned",
                    generated_at=fixture.kickoff_at,
                ),
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    result = runner.invoke(
        app,
        [
            "match-brief",
            "--fixture-id",
            fixture.fixture_id,
            "--query",
            "Should I back Arsenal?",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["fixture_id"] == fixture.fixture_id
    assert payload["status"] == "succeeded"
    assert payload["fixture"]["home_team"] == "Arsenal"
    assert payload["judgment"]["verdict"] == "Lean Arsenal pre-match."
    assert payload["judgment"]["confidence"] == "medium"
    assert payload["evidence"]["tactical_summary"] == ["Arsenal can press high."]
    assert payload["agent"]["nodes"] == ["classify_intent", "analyze_match", "synthesize_result"]
    assert payload["generated_synthesis"] == "Lean Arsenal pre-match. Confidence: medium."
    assert "core_reasons" in payload["sections"]
    assert "market_evidence" in payload["sections"]


def test_match_brief_command_text_renders_operator_brief(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="succeeded",
                nodes=["classify_intent", "analyze_match", "synthesize_result"],
                analysis=FixtureAnalysisResult(
                    fixture=fixture,
                    intent=QueryIntent.DECISIONAL,
                    query=query,
                    evidence=AnalysisEvidenceSummary(
                        tactical_summary=["Arsenal can press high."],
                        snapshot_summary=["Arsenal squad edge."],
                        odds_summary=["Market fair view leans Arsenal."],
                        market_shape_summary=[],
                        caveats=["Derby variance remains elevated."],
                    ),
                    judgment=AnalysisJudgment(
                        verdict="Lean Arsenal pre-match.",
                        core_reasons=["Pressing edge"],
                        counterargument="Tottenham transition threat remains live.",
                        confidence="medium",
                    ),
                    conflict_state="aligned",
                    generated_at=fixture.kickoff_at,
                ),
                generated_synthesis="Lean Arsenal pre-match. Confidence: medium.",
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    result = runner.invoke(
        app,
        ["match-brief", "--fixture-id", fixture.fixture_id, "--query", "Should I back Arsenal?"],
    )

    assert result.exit_code == 0
    assert "Match Brief: Arsenal vs Tottenham Hotspur" in result.stdout
    assert "Verdict: Lean Arsenal pre-match." in result.stdout
    assert "Confidence: medium" in result.stdout
    assert "Core reasons:" in result.stdout
    assert "Pressing edge" in result.stdout
    assert "Tactical evidence:" in result.stdout
    assert "Market evidence:" in result.stdout
    assert "Caveats:" in result.stdout
    assert "Generated synthesis:" in result.stdout


def test_match_brief_command_preserves_workflow_failure(monkeypatch) -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.interfaces import cli as cli_module

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="failed",
                nodes=["classify_intent", "analyze_match"],
                error="Not enough evidence for a direct call.",
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    json_result = runner.invoke(
        app,
        [
            "match-brief",
            "--fixture-id",
            "epl-001",
            "--query",
            "Should I back Arsenal?",
            "--format",
            "json",
        ],
    )
    text_result = runner.invoke(
        app,
        ["match-brief", "--fixture-id", "epl-001", "--query", "Should I back Arsenal?"],
    )
    payload = json.loads(json_result.stdout)

    assert json_result.exit_code == 2
    assert payload["status"] == "failed"
    assert payload["error"] == "Not enough evidence for a direct call."
    assert payload["sections"] == {}
    assert text_result.exit_code == 2
    assert "Not enough evidence for a direct call." in text_result.stdout


def test_bot_dry_run_command_text_and_json(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixture = sample_fixtures("epl")[0]

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="succeeded",
                nodes=["classify_intent", "analyze_match"],
                analysis=FixtureAnalysisResult(
                    fixture=fixture,
                    intent=QueryIntent.DECISIONAL,
                    query=query,
                    evidence=AnalysisEvidenceSummary(
                        tactical_summary=["Arsenal can press high."],
                        snapshot_summary=[],
                        odds_summary=["Market fair view leans Arsenal."],
                        market_shape_summary=[],
                        caveats=[],
                    ),
                    judgment=AnalysisJudgment(
                        verdict="Lean Arsenal pre-match.",
                        core_reasons=["Pressing edge"],
                        counterargument="Spurs transition threat remains live.",
                        confidence="medium",
                    ),
                    conflict_state="aligned",
                    generated_at=fixture.kickoff_at,
                ),
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    text_result = runner.invoke(
        app,
        ["bot-dry-run", "--message", "/brief epl-001 Should I back Arsenal?"],
    )
    json_result = runner.invoke(
        app,
        [
            "bot-dry-run",
            "--message",
            "/brief epl-001 Should I back Arsenal?",
            "--format",
            "json",
        ],
    )
    payload = json.loads(json_result.stdout)

    assert text_result.exit_code == 0
    assert "Arsenal vs Tottenham Hotspur" in text_result.stdout
    assert "Lean Arsenal pre-match." in text_result.stdout
    assert json_result.exit_code == 0
    assert payload["status"] == "succeeded"
    assert payload["payload"]["fixture_id"] == "epl-001"


def test_bot_dry_run_command_failure_exits_nonzero(monkeypatch) -> None:
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.interfaces import cli as cli_module

    monkeypatch.setenv("NUTMEG_BOT_LLM_FALLBACK_ENABLED", "false")
    clear_settings_cache()

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="failed",
                nodes=["classify_intent", "analyze_match"],
                error="Not enough evidence for a direct call.",
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    result = runner.invoke(
        app,
        ["bot-dry-run", "--message", "/brief epl-001 Should I back Arsenal?"],
    )

    assert result.exit_code == 2
    assert "Not enough evidence for a direct call." in result.stdout


def test_bot_dry_run_command_uses_llm_fallback_for_plain_message(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):  # pragma: no cover
            raise AssertionError("workflow should not run for plain fallback message")

    class StubFallback:
        def respond(self, message: str, *, error: str | None = None) -> str:
            assert message == "今天有哪些热门比赛？"
            assert error == "Unsupported bot command. Try `/brief <fixture_id> <query>`."
            return "先运行 popular-matches，再选择 fixture_id 用 /brief 深挖。"

    monkeypatch.setenv("NUTMEG_OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("NUTMEG_BOT_LLM_FALLBACK_ENABLED", "true")
    clear_settings_cache()
    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))
    monkeypatch.setattr(
        cli_module,
        "build_bot_fallback_provider",
        lambda settings: StubFallback(),
    )

    result = runner.invoke(
        app,
        ["bot-dry-run", "--message", "今天有哪些热门比赛？", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["status"] == "succeeded"
    assert payload["payload"]["mode"] == "llm_fallback"
    assert "popular-matches" in payload["text"]
    assert "openai-secret" not in result.stdout


def test_today_briefs_command_lists_demo_fixture_candidates() -> None:
    result = runner.invoke(app, ["today-briefs", "--league", "epl", "--days", "3", "--demo"])

    assert result.exit_code == 0
    assert "Today brief candidates: epl" in result.stdout
    assert "epl-001" in result.stdout
    assert "Arsenal vs Tottenham Hotspur" in result.stdout
    assert "/brief epl-001" in result.stdout


def test_popular_matches_command_returns_ranked_demo_candidates() -> None:
    result = runner.invoke(
        app,
        ["popular-matches", "--league", "epl", "--days", "3", "--demo", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["league"] == "epl"
    assert payload["sort"] == "popularity"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["rank"] == 1
    assert payload["items"][0]["popularity"]["score"] >= payload["items"][1]["popularity"]["score"]
    assert payload["items"][0]["popularity"]["tier"] in {"headline", "strong", "watchlist"}
    assert payload["items"][0]["popularity"]["reasons"]
    assert payload["items"][0]["suggested_bot_message"].startswith("/brief ")


def test_value_board_command_returns_json_contract(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.value import ValueBoard, ValueCandidate
    from nutmeg.interfaces import cli as cli_module

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeValueBoardService:
        def build_board(self, *, league: str, days: int, limit: int, min_edge: float):
            assert league == "epl"
            assert days == 3
            assert limit == 5
            assert min_edge == 0.03
            return ValueBoard(
                league="epl",
                days=3,
                generated_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
                candidates=[
                    ValueCandidate(
                        fixture_id="fx-1",
                        kickoff_at=datetime(2026, 4, 25, 15, 0, tzinfo=UTC),
                        home_team="Arsenal",
                        away_team="Tottenham Hotspur",
                        outcome_key="home",
                        outcome_name="Home",
                        model_probability=0.56,
                        market_probability=0.45,
                        edge=0.11,
                        best_odds=2.2,
                        expected_value=0.232,
                        quarter_kelly_fraction=0.048,
                        rating="strong",
                        model_name="dixon-coles-lite-poisson",
                        source_notes=["model=recent-xg-matchup", "odds=test-odds"],
                    )
                ],
                skipped=[],
            )

    session = FakeSession()
    monkeypatch.setattr(
        cli_module,
        "build_value_board_service",
        lambda: (FakeValueBoardService(), session),
    )

    result = runner.invoke(
        app,
        [
            "value-board",
            "--league",
            "epl",
            "--days",
            "3",
            "--limit",
            "5",
            "--min-edge",
            "0.03",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert session.closed is True
    assert payload["league"] == "epl"
    assert payload["candidates"][0]["fixture_id"] == "fx-1"
    assert payload["candidates"][0]["edge"] == 0.11
    assert payload["candidates"][0]["quarter_kelly_fraction"] == 0.048


def test_player_profile_command_returns_json_contract(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.players import (
        PlayerAvailability,
        PlayerIdentityProfile,
        PlayerMarketProfile,
        PlayerProfile,
        PlayerSeasonMetrics,
        SimilarPlayer,
    )
    from nutmeg.interfaces import cli as cli_module

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakePlayerProfileService:
        def build_profile(
            self,
            *,
            league: str,
            season: int | None,
            team: str,
            player: str,
            similar_limit: int = 5,
        ):
            assert league == "epl"
            assert season == 2025
            assert team == "Arsenal"
            assert player == "Bukayo Saka"
            assert similar_limit == 3
            return PlayerProfile(
                query_player="Bukayo Saka",
                query_team="Arsenal",
                league="epl",
                season=2025,
                generated_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
                identity=PlayerIdentityProfile(
                    identity_id="epl:arsenal:bukayo-saka",
                    canonical_name="Bukayo Saka",
                    team_name="Arsenal",
                    match_confidence="catalog",
                ),
                market=PlayerMarketProfile(
                    provider_player_id="7",
                    position="Right Winger",
                    market_value_eur=140000000,
                    source="transfermarkt-datasets",
                ),
                season_metrics=PlayerSeasonMetrics(
                    source="soccerdata-cache",
                    minutes=2500,
                    goals_per90=0.42,
                    assists_per90=0.33,
                    xg_per90=0.48,
                    xa_per90=0.30,
                    key_passes_per90=2.4,
                    duels_won_per90=3.2,
                ),
                availability=PlayerAvailability(
                    status="available",
                    reason=None,
                    expected_return=None,
                    source="local-cache",
                ),
                similar_players=[
                    SimilarPlayer(
                        player_name="Phil Foden",
                        team_name="Manchester City",
                        position="Right Winger",
                        similarity_score=0.98,
                        source="soccerdata-cache",
                    )
                ],
                unavailable_sections=[],
            )

    session = FakeSession()
    monkeypatch.setattr(
        cli_module,
        "build_player_profile_service",
        lambda: (FakePlayerProfileService(), session),
    )

    result = runner.invoke(
        app,
        [
            "player-profile",
            "--league",
            "epl",
            "--season",
            "2025",
            "--team",
            "Arsenal",
            "--player",
            "Bukayo Saka",
            "--similar-limit",
            "3",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert session.closed is True
    assert payload["identity"]["canonical_name"] == "Bukayo Saka"
    assert payload["market"]["market_value_eur"] == 140000000
    assert payload["season_metrics"]["xg_per90"] == 0.48
    assert payload["similar_players"][0]["player_name"] == "Phil Foden"


def test_eval_run_command_returns_json_contract(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.evals import EvalCaseResult, EvalRunResult
    from nutmeg.interfaces import cli as cli_module

    class FakeEvalService:
        def run_dataset(self, dataset: str):
            assert dataset == "starter"
            return EvalRunResult(
                dataset="starter",
                generated_at=datetime(2026, 4, 25, 11, 0, tzinfo=UTC),
                total_cases=1,
                passed_cases=1,
                failed_cases=0,
                results=[
                    EvalCaseResult(
                        case_id="case-1",
                        category="odds",
                        passed=True,
                        missing_keywords=[],
                        output_text="判断：edge. 置信度：中。",
                    )
                ],
            )

    monkeypatch.setattr(cli_module, "build_eval_service", lambda: FakeEvalService())

    result = runner.invoke(app, ["eval-run", "--dataset", "starter", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["dataset"] == "starter"
    assert payload["passed_cases"] == 1
    assert payload["results"][0]["passed"] is True


def test_prediction_review_command_returns_json_contract(monkeypatch) -> None:
    from nutmeg.domain.evals import PredictionReviewSummary
    from nutmeg.interfaces import cli as cli_module

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakePredictionRepository:
        def review(self, *, user_id: str):
            assert user_id == "owner"
            return PredictionReviewSummary(
                total_predictions=3,
                resolved_predictions=2,
                average_brier_score=0.31,
                pick_accuracy=0.5,
            )

    session = FakeSession()
    monkeypatch.setattr(
        cli_module,
        "build_prediction_repository",
        lambda: (FakePredictionRepository(), session),
    )

    result = runner.invoke(app, ["prediction-review", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert session.closed is True
    assert payload["resolved_predictions"] == 2
    assert payload["average_brier_score"] == 0.31


def test_daily_run_command_returns_json_contract(monkeypatch) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.operations import (
        DailyRunSummary,
        OperationBrief,
        OperationPopularMatch,
        TelegramDispatch,
        TelegramDispatchStatus,
    )
    from nutmeg.domain.value import ValueCandidate
    from nutmeg.interfaces import cli as cli_module

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False
            self.committed = False

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            self.closed = True

    class FakeDailyOperatorService:
        def run(
            self,
            *,
            league: str,
            days: int,
            limit: int,
            query: str,
            dry_run: bool,
            live_sync: bool,
            briefs: bool,
            dispatch_telegram: bool,
        ):
            assert league == "epl"
            assert days == 3
            assert limit == 5
            assert dry_run is True
            assert live_sync is False
            assert briefs is False
            assert dispatch_telegram is False
            return DailyRunSummary(
                league="epl",
                days=3,
                generated_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
                dry_run=True,
                live_sync=False,
                sync_status="skipped",
                sync_fixtures_written=0,
                sync_requests_made=0,
                fixtures_considered=2,
                popular_matches=[
                    OperationPopularMatch(
                        fixture_id="epl-001",
                        rank=1,
                        home_team="Arsenal",
                        away_team="Tottenham Hotspur",
                        score=108,
                        tier="headline",
                    )
                ],
                value_candidates=[
                    ValueCandidate(
                        fixture_id="epl-001",
                        kickoff_at=datetime(2026, 4, 25, 15, 0, tzinfo=UTC),
                        home_team="Arsenal",
                        away_team="Tottenham Hotspur",
                        outcome_key="home",
                        outcome_name="Home",
                        model_probability=0.56,
                        market_probability=0.45,
                        edge=0.11,
                        best_odds=2.2,
                        expected_value=0.232,
                        quarter_kelly_fraction=0.048,
                        rating="strong",
                        model_name="dixon-coles-lite-poisson",
                        source_notes=["test"],
                    )
                ],
                briefs=[OperationBrief(fixture_id="epl-001", status="skipped")],
                telegram_dispatch=TelegramDispatch(status=TelegramDispatchStatus.SKIPPED),
            )

    session = FakeSession()
    monkeypatch.setattr(
        cli_module,
        "build_daily_operator_service",
        lambda: (FakeDailyOperatorService(), session),
    )

    result = runner.invoke(
        app,
        ["daily-run", "--league", "epl", "--days", "3", "--limit", "5", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert session.committed is True
    assert session.closed is True
    assert payload["sync_status"] == "skipped"
    assert payload["popular_matches"][0]["fixture_id"] == "epl-001"
    assert payload["value_candidates"][0]["edge"] == 0.11


def test_tactical_visuals_command_returns_json_contract(monkeypatch, tmp_path) -> None:
    from datetime import UTC, datetime

    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.domain.tactics import TacticalVisualArtifact, TacticalVisualPack
    from nutmeg.interfaces import cli as cli_module

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeTacticalVisualService:
        def build_pack(self, fixture_id: str, *, output_dir=None):
            assert fixture_id == "epl-001"
            assert output_dir == tmp_path
            return TacticalVisualPack(
                fixture=sample_fixtures("epl")[0],
                generated_at=datetime(2026, 4, 25, 13, 0, tzinfo=UTC),
                artifacts=[
                    TacticalVisualArtifact(
                        name="shot-map",
                        title="Shot Map Proxy",
                        status="proxy",
                        format="svg",
                        svg="<svg><text>Shot Map</text></svg>",
                        source="snapshot-shot-summary",
                        description="aggregate shot map proxy",
                        path="epl-001-shot-map.svg",
                    )
                ],
                insights=["Arsenal carry the stronger xG trend."],
                unavailable_sections=[],
            )

    session = FakeSession()
    monkeypatch.setattr(
        cli_module,
        "build_tactical_visual_service",
        lambda: (FakeTacticalVisualService(), session),
    )

    result = runner.invoke(
        app,
        [
            "tactical-visuals",
            "--fixture-id",
            "epl-001",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert session.closed is True
    assert payload["artifacts"][0]["name"] == "shot-map"
    assert payload["artifacts"][0]["path"] == "epl-001-shot-map.svg"
    assert payload["insights"]


def test_today_briefs_command_can_sort_by_popularity() -> None:
    result = runner.invoke(
        app,
        [
            "today-briefs",
            "--league",
            "epl",
            "--days",
            "3",
            "--demo",
            "--sort",
            "popularity",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["sort"] == "popularity"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["rank"] == 1
    assert payload["items"][0]["popularity"]["score"] >= payload["items"][1]["popularity"]["score"]
    assert payload["items"][0]["popularity"]["reasons"]


def test_today_briefs_command_json_generates_briefs(monkeypatch) -> None:
    from nutmeg.agents.router import QueryIntent
    from nutmeg.agents.workflow import MatchAnalysisAgentResult
    from nutmeg.domain.analysis import (
        AnalysisEvidenceSummary,
        AnalysisJudgment,
        FixtureAnalysisResult,
    )
    from nutmeg.domain.fixtures import sample_fixtures
    from nutmeg.interfaces import cli as cli_module

    fixtures = {fixture.fixture_id: fixture for fixture in sample_fixtures("epl")}

    class StubWorkflow:
        def run(self, *, fixture_id: str, query: str):
            fixture = fixtures[fixture_id]
            return MatchAnalysisAgentResult(
                fixture_id=fixture_id,
                query=query,
                status="succeeded",
                nodes=["classify_intent", "analyze_match"],
                analysis=FixtureAnalysisResult(
                    fixture=fixture,
                    intent=QueryIntent.DECISIONAL,
                    query=query,
                    evidence=AnalysisEvidenceSummary(
                        tactical_summary=[f"{fixture.home_team} tactical edge."],
                        snapshot_summary=[],
                        odds_summary=["Market fair view is available."],
                        market_shape_summary=[],
                        caveats=[],
                    ),
                    judgment=AnalysisJudgment(
                        verdict=f"Lean {fixture.home_team} pre-match.",
                        core_reasons=["Home structure edge"],
                        counterargument="Variance remains live.",
                        confidence="medium",
                    ),
                    conflict_state="aligned",
                    generated_at=fixture.kickoff_at,
                ),
            )

    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (StubWorkflow(), None))

    result = runner.invoke(
        app,
        [
            "today-briefs",
            "--league",
            "epl",
            "--days",
            "3",
            "--demo",
            "--briefs",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["league"] == "epl"
    assert payload["briefs_requested"] is True
    assert len(payload["items"]) == 2
    assert payload["items"][0]["brief"]["status"] == "succeeded"
    assert payload["items"][0]["brief"]["judgment"]["confidence"] == "medium"
    assert payload["items"][0]["suggested_bot_message"].startswith("/brief epl-001")


def test_today_briefs_command_json_reports_empty_local_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NUTMEG_DATA_DIR", str(tmp_path / "nutmeg-data"))
    clear_settings_cache()

    result = runner.invoke(
        app,
        ["today-briefs", "--league", "epl", "--days", "1", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["league"] == "epl"
    assert payload["items"] == []
    assert payload["empty_reason"] == (
        "No local fixtures available. Run fixtures-sync or use --demo."
    )


def test_telegram_bot_status_reports_configuration_without_token(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111,222")
    clear_settings_cache()

    result = runner.invoke(app, ["telegram-bot-status", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["configured"] is True
    assert payload["allowed_chat_count"] == 2
    assert payload["allowed_chat_ids_configured"] is True
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_poll_once_uses_runner_builder(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        updates_seen = 2
        messages_handled = 1
        messages_denied = 1
        messages_ignored = 0
        next_offset = 12

    class StubRunner:
        def poll_once(self, *, offset: int | None, timeout: int):
            assert offset == 10
            assert timeout == 1
            return StubSummary()

    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(cli_module, "build_telegram_bot_runner", lambda settings: StubRunner())

    result = runner.invoke(
        app,
        ["telegram-bot-poll-once", "--offset", "10", "--timeout", "1", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["updates_seen"] == 2
    assert payload["messages_handled"] == 1
    assert payload["messages_denied"] == 1
    assert payload["next_offset"] == 12
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_uses_daemon_builder(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 2
        updates_seen = 3
        messages_handled = 2
        messages_denied = 1
        messages_ignored = 0
        next_offset = 13
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 10
            assert timeout == 1
            assert max_polls == 2
            return StubSummary()

    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--offset",
            "10",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "2",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["polls_run"] == 2
    assert payload["updates_seen"] == 3
    assert payload["messages_handled"] == 2
    assert payload["messages_denied"] == 1
    assert payload["next_offset"] == 13
    assert payload["stop_reason"] == "max_polls"
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_uses_stored_offset_when_offset_omitted(monkeypatch, tmp_path) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 1
        updates_seen = 0
        messages_handled = 0
        messages_denied = 0
        messages_ignored = 0
        next_offset = 100
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 99
            assert timeout == 1
            assert max_polls == 1
            return StubSummary()

    offset_file = tmp_path / "telegram.offset"
    offset_file.write_text("99\n")
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "1",
            "--offset-file",
            str(offset_file),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["offset_source"] == "store"
    assert payload["offset_file"] == str(offset_file)
    assert payload["offset_persistence_enabled"] is True
    assert payload["next_offset"] == 100
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_explicit_offset_overrides_stored_offset(monkeypatch, tmp_path) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 1
        updates_seen = 0
        messages_handled = 0
        messages_denied = 0
        messages_ignored = 0
        next_offset = 11
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 10
            return StubSummary()

    offset_file = tmp_path / "telegram.offset"
    offset_file.write_text("99\n")
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--offset",
            "10",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "1",
            "--offset-file",
            str(offset_file),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["offset_source"] == "explicit"
    assert payload["next_offset"] == 11


def test_client_commands_are_registered_in_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    commands = [
        "client-alerts",
        "client-feed",
        "client-match",
        "client-prediction-record",
        "client-question",
        "client-status",
        "client-watchlist",
        "client-web",
    ]
    for command in commands:
        assert command in result.stdout


def test_client_status_command_returns_json_contract(monkeypatch) -> None:
    class FakeClientService:
        def status(self, user_id=None):
            return {
                "user_id": user_id or "owner",
                "health": {"health": "healthy", "blocking_reasons": []},
                "providers": {},
                "entitlements": {"plan": "owner"},
                "responsible_use": "分析仅供参考，不构成投注建议。",
            }

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_client_service", lambda: (FakeClientService(), None))

    result = runner.invoke(app, ["client-status", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["user_id"] == "owner"
    assert payload["health"]["health"] == "healthy"


def test_client_feed_command_returns_json_contract(monkeypatch) -> None:
    class FakeClientService:
        def daily_feed(self, *, user_id=None, league="epl", days=3, limit=5, demo=False):
            return {
                "user_id": user_id or "owner",
                "league": league,
                "days": days,
                "generated_at": "2026-04-26T00:00:00+00:00",
                "opportunities": [
                    {
                        "fixture_id": "epl-001",
                        "actionability": "value",
                        "freshness": {"health": "healthy", "blocking_reasons": []},
                    }
                ],
                "health": {"health": "healthy", "blocking_reasons": []},
                "responsible_use": "分析仅供参考，不构成投注建议。",
            }

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_client_service", lambda: (FakeClientService(), None))

    result = runner.invoke(
        app,
        ["client-feed", "--league", "epl", "--days", "3", "--demo", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["opportunities"][0]["fixture_id"] == "epl-001"
    assert payload["opportunities"][0]["actionability"] == "value"


def test_client_match_command_returns_json_contract(monkeypatch) -> None:
    class FakeClientService:
        def match_workspace(self, *, user_id=None, fixture_id):
            return {
                "fixture_id": fixture_id,
                "actionability": "value",
                "judgment": {"verdict": "Lean Arsenal pre-match.", "confidence": "high"},
                "evidence": [{"source_name": "Nutmeg match brief"}],
                "freshness": {"health": "healthy", "blocking_reasons": []},
                "caveats": [],
                "audit_id": "audit-1",
                "responsible_use": "分析仅供参考，不构成投注建议。",
            }

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_client_service", lambda: (FakeClientService(), None))

    result = runner.invoke(app, ["client-match", "--fixture-id", "epl-001", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["fixture_id"] == "epl-001"
    assert payload["judgment"]["verdict"] == "Lean Arsenal pre-match."
    assert payload["audit_id"] == "audit-1"


def test_client_question_command_returns_json_contract(monkeypatch) -> None:
    class FakeClientService:
        def answer_question(self, *, user_id=None, fixture_id, question):
            return {
                "answer": "Lean Arsenal pre-match. Evidence remains grounded.",
                "confidence": "high",
                "evidence": [{"source_name": "Nutmeg match brief"}],
                "refused": False,
                "refusal_reason": None,
            }

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_client_service", lambda: (FakeClientService(), None))

    result = runner.invoke(
        app,
        [
            "client-question",
            "--fixture-id",
            "epl-001",
            "--question",
            "what changed?",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["refused"] is False
    assert "Lean Arsenal pre-match." in payload["answer"]


def test_client_status_command_returns_entitlement_for_requested_user(monkeypatch) -> None:
    class FakeClientService:
        def status(self, user_id=None):
            return {
                "user_id": user_id or "owner",
                "health": {"health": "healthy", "blocking_reasons": []},
                "providers": {},
                "entitlements": {
                    "plan": "basic",
                    "premium_match_detail_enabled": False,
                },
                "responsible_use": "分析仅供参考，不构成投注建议。",
            }

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_client_service", lambda: (FakeClientService(), None))

    result = runner.invoke(app, ["client-status", "--user-id", "guest", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["user_id"] == "guest"
    assert payload["entitlements"]["plan"] == "basic"
    assert payload["entitlements"]["premium_match_detail_enabled"] is False


def test_client_watchlist_alert_and_prediction_commands_return_json(monkeypatch) -> None:
    class FakeClientService:
        def save_watchlist_item(self, *, user_id, target_type, target_id, alert_preferences=None):
            return {
                "watchlist_id": "watch-1",
                "user_id": user_id,
                "target_type": target_type,
                "target_id": target_id,
                "alert_preferences": alert_preferences or [],
            }

        def alerts(self, *, user_id):
            return {"alerts": [{"alert_id": "alert-1", "change_type": "odds"}]}

        def record_prediction(
            self,
            *,
            user_id,
            fixture_id,
            pick,
            source_audit_id=None,
            client_notes=None,
        ):
            return {
                "prediction_id": 42,
                "fixture_id": fixture_id,
                "pick": pick,
                "source_audit_id": source_audit_id,
                "status": "recorded",
            }

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_client_service", lambda: (FakeClientService(), None))

    watch = runner.invoke(
        app,
        [
            "client-watchlist",
            "--target-type",
            "fixture",
            "--target-id",
            "epl-001",
            "--alert-preference",
            "odds",
            "--format",
            "json",
        ],
    )
    alerts = runner.invoke(app, ["client-alerts", "--format", "json"])
    prediction = runner.invoke(
        app,
        [
            "client-prediction-record",
            "--fixture-id",
            "epl-001",
            "--pick",
            "home",
            "--source-audit-id",
            "audit-1",
            "--format",
            "json",
        ],
    )

    assert json.loads(watch.stdout)["watchlist_id"] == "watch-1"
    assert json.loads(alerts.stdout)["alerts"][0]["change_type"] == "odds"
    assert json.loads(prediction.stdout)["prediction_id"] == 42


def test_event_tactical_models_command_is_registered_in_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "event-tactical-models" in result.stdout


def test_event_tactical_models_command_returns_json_contract(monkeypatch, tmp_path) -> None:
    class FakeReport:
        def to_dict(self):
            return {
                "fixture_id": "epl-001",
                "quality": {
                    "fixture_id": "epl-001",
                    "provider": "test-provider",
                    "status": "complete",
                    "event_count": 12,
                    "teams": ["Arsenal"],
                    "players": ["Arsenal 6"],
                    "warnings": [],
                    "generated_at": "2026-04-26T00:00:00+00:00",
                },
                "pass_network": {
                    "model_label": "pass-network-from-events-v0",
                    "nodes": [],
                    "edges": [],
                    "warnings": [],
                },
                "spatial_value": {
                    "model_label": "xT-lite-v0",
                    "pitch": {"length": 120, "width": 80},
                    "grid": [],
                    "actions": [],
                    "players": [],
                    "warnings": [],
                },
                "player_contributions": {
                    "model_label": "VAEP-lite-heuristic-v0",
                    "players": [],
                    "warnings": ["not trained VAEP"],
                },
                "artifacts": [
                    {
                        "artifact_id": "epl-001-pass-network",
                        "title": "Pass Network",
                        "kind": "pass_network",
                        "description": "Completed pass network from event data.",
                        "svg": "<svg></svg>",
                        "file_path": str(tmp_path / "epl-001-pass-network.svg"),
                    }
                ],
                "unavailable_sections": [],
                "warnings": ["xT-lite-v0 is deterministic heuristic, not trained xT."],
                "generated_at": "2026-04-26T00:00:00+00:00",
            }

    class FakeService:
        def build_report(self, *, fixture_id, events_file=None, output_dir=None):
            assert fixture_id == "epl-001"
            assert output_dir == tmp_path
            return FakeReport()

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_event_tactical_model_service", lambda: FakeService())

    result = runner.invoke(
        app,
        [
            "event-tactical-models",
            "--fixture-id",
            "epl-001",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["quality"]["event_count"] == 12
    assert payload["spatial_value"]["model_label"] == "xT-lite-v0"
    assert payload["player_contributions"]["model_label"] == "VAEP-lite-heuristic-v0"
    assert payload["artifacts"][0]["file_path"].endswith("epl-001-pass-network.svg")


def test_event_tactical_models_command_returns_unavailable_json(monkeypatch) -> None:
    class FakeReport:
        def to_dict(self):
            return {
                "fixture_id": "missing-fixture",
                "quality": {
                    "fixture_id": "missing-fixture",
                    "provider": "test-provider",
                    "status": "unavailable",
                    "event_count": 0,
                    "teams": [],
                    "players": [],
                    "warnings": ["event data unavailable"],
                    "generated_at": "2026-04-26T00:00:00+00:00",
                },
                "pass_network": {
                    "model_label": "pass-network-from-events-v0",
                    "nodes": [],
                    "edges": [],
                    "warnings": [],
                },
                "spatial_value": {
                    "model_label": "xT-lite-v0",
                    "pitch": {"length": 120, "width": 80},
                    "grid": [],
                    "actions": [],
                    "players": [],
                    "warnings": [],
                },
                "player_contributions": {
                    "model_label": "VAEP-lite-heuristic-v0",
                    "players": [],
                    "warnings": [],
                },
                "artifacts": [],
                "unavailable_sections": ["pass_network", "spatial_value", "player_contributions"],
                "warnings": ["event data unavailable"],
                "generated_at": "2026-04-26T00:00:00+00:00",
            }

    class FakeService:
        def build_report(self, *, fixture_id, events_file=None, output_dir=None):
            return FakeReport()

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_event_tactical_model_service", lambda: FakeService())

    result = runner.invoke(
        app,
        ["event-tactical-models", "--fixture-id", "missing-fixture", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["quality"]["status"] == "unavailable"
    assert payload["artifacts"] == []


def test_fixture_information_command_is_registered_in_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "fixture-information" in result.stdout


def test_fixture_information_command_returns_json_contract(monkeypatch, tmp_path) -> None:
    class FakeDigest:
        def to_dict(self):
            return {
                "fixture_id": "epl-001",
                "status": "complete",
                "summary": "1 relevant update from 1 source.",
                "source_count": 1,
                "latest_published_at": "2026-04-26T09:00:00+00:00",
                "items": [
                    {
                        "item_id": "info-1",
                        "source_name": "Club official",
                        "source_type": "json",
                        "title": "Arsenal defender fit",
                        "summary": "Official training note.",
                        "url": "https://example.test/info-1",
                        "published_at": "2026-04-26T09:00:00+00:00",
                        "retrieved_at": "2026-04-26T09:05:00+00:00",
                        "reliability": "official",
                        "fixture_ids": ["epl-001"],
                        "teams": ["Arsenal"],
                        "tags": ["injury"],
                        "metadata": {},
                    }
                ],
                "warnings": [],
                "source_health": [],
                "generated_at": "2026-04-26T09:05:00+00:00",
            }

    class FakeService:
        def build_digest(self, *, fixture_id, home_team=None, away_team=None, sources_file=None):
            assert fixture_id == "epl-001"
            assert home_team == "Arsenal"
            assert sources_file == tmp_path
            return FakeDigest()

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_fixture_information_service", lambda: FakeService())

    result = runner.invoke(
        app,
        [
            "fixture-information",
            "--fixture-id",
            "epl-001",
            "--home-team",
            "Arsenal",
            "--sources-file",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "complete"
    assert payload["items"][0]["source_name"] == "Club official"
    assert payload["latest_published_at"] == "2026-04-26T09:00:00+00:00"


def test_fixture_information_command_returns_unavailable_json(monkeypatch) -> None:
    class FakeDigest:
        def to_dict(self):
            return {
                "fixture_id": "missing",
                "status": "unavailable",
                "summary": "Information unavailable.",
                "source_count": 0,
                "latest_published_at": None,
                "items": [],
                "warnings": ["source file missing"],
                "source_health": [],
                "generated_at": "2026-04-26T09:05:00+00:00",
            }

    class FakeService:
        def build_digest(self, *, fixture_id, home_team=None, away_team=None, sources_file=None):
            return FakeDigest()

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_fixture_information_service", lambda: FakeService())

    result = runner.invoke(
        app,
        ["fixture-information", "--fixture-id", "missing", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "unavailable"
    assert payload["items"] == []


def test_fixture_information_command_accepts_live_manifest_flags(monkeypatch, tmp_path) -> None:
    calls = {}

    class FakeDigest:
        def to_dict(self):
            return {
                "fixture_id": "epl-001",
                "status": "complete",
                "summary": "Live source update.",
                "source_count": 1,
                "latest_published_at": "2026-04-26T09:00:00+00:00",
                "items": [
                    {
                        "title": "Live Arsenal note",
                        "source_name": "Club RSS",
                        "reliability": "official",
                    }
                ],
                "warnings": [],
                "source_health": [
                    {"source_name": "Club RSS", "status": "complete", "warnings": []}
                ],
                "generated_at": "2026-04-26T09:05:00+00:00",
            }

    class FakeService:
        def build_digest(self, *, fixture_id, home_team=None, away_team=None, sources_file=None):
            calls["build_digest"] = {
                "fixture_id": fixture_id,
                "home_team": home_team,
                "away_team": away_team,
                "sources_file": sources_file,
            }
            return FakeDigest()

    import nutmeg.interfaces.cli as cli

    def fake_builder(**kwargs):
        calls["builder"] = kwargs
        return FakeService()

    monkeypatch.setattr(cli, "build_live_fixture_information_service", fake_builder)

    config = tmp_path / "sources.json"
    cache_dir = tmp_path / "cache"
    result = runner.invoke(
        app,
        [
            "fixture-information",
            "--fixture-id",
            "epl-001",
            "--home-team",
            "Arsenal",
            "--away-team",
            "Tottenham Hotspur",
            "--sources-config",
            str(config),
            "--cache-dir",
            str(cache_dir),
            "--live-fetch",
            "--cache-ttl-seconds",
            "30",
            "--timeout-seconds",
            "2.5",
            "--max-bytes",
            "4096",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["items"][0]["title"] == "Live Arsenal note"
    assert calls["builder"]["manifest_path"] == config
    assert calls["builder"]["cache_dir"] == cache_dir
    assert calls["builder"]["live_fetch"] is True
    assert calls["builder"]["cache_ttl_seconds"] == 30
    assert calls["builder"]["timeout_seconds"] == 2.5
    assert calls["builder"]["max_bytes"] == 4096
    assert calls["build_digest"]["sources_file"] is None


def test_fixture_information_command_live_manifest_unavailable_json(monkeypatch, tmp_path) -> None:
    class FakeDigest:
        def to_dict(self):
            return {
                "fixture_id": "epl-001",
                "status": "unavailable",
                "summary": "Information unavailable.",
                "source_count": 0,
                "latest_published_at": None,
                "items": [],
                "warnings": ["remote fetch disabled and no fresh cache"],
                "source_health": [],
                "generated_at": "2026-04-26T09:05:00+00:00",
            }

    class FakeService:
        def build_digest(self, *, fixture_id, home_team=None, away_team=None, sources_file=None):
            return FakeDigest()

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(
        cli,
        "build_live_fixture_information_service",
        lambda **kwargs: FakeService(),
    )

    result = runner.invoke(
        app,
        [
            "fixture-information",
            "--fixture-id",
            "epl-001",
            "--sources-config",
            str(tmp_path / "missing.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "unavailable"
    assert payload["items"] == []
    assert "remote fetch disabled" in payload["warnings"][0]


def test_client_match_command_can_use_live_information_manifest(monkeypatch, tmp_path) -> None:
    calls = {}

    class FakeInformationService:
        def build_information(self, fixture_id, *, home_team=None, away_team=None):
            return {
                "summary": "Manifest-backed live info.",
                "status": "complete",
                "items": [{"title": "Live info"}],
                "warnings": [],
            }

    class FakeClientService:
        def set_information_provider(self, provider):
            calls["provider"] = provider

        def match_workspace(self, *, user_id=None, fixture_id):
            return {
                "fixture_id": fixture_id,
                "user_id": user_id or "owner",
                "actionability": "watch",
                "judgment": {"confidence": "low", "verdict": "Watch only."},
                "information": calls["provider"].build_information(fixture_id),
            }

    import nutmeg.interfaces.cli as cli

    monkeypatch.setattr(cli, "build_client_service", lambda: (FakeClientService(), None))
    monkeypatch.setattr(
        cli,
        "build_live_fixture_information_service",
        lambda **kwargs: FakeInformationService(),
    )

    result = runner.invoke(
        app,
        [
            "client-match",
            "--fixture-id",
            "epl-001",
            "--information-sources-config",
            str(tmp_path / "sources.json"),
            "--information-cache-dir",
            str(tmp_path / "cache"),
            "--live-information-fetch",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["information"]["summary"] == "Manifest-backed live info."
    assert calls["provider"].__class__.__name__ == "FakeInformationService"


def test_zucai_report_command_generates_json_artifacts_and_dry_run_dispatch(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    result = runner.invoke(
        app,
        [
            "zucai-report",
            "--issue-id",
            "26068",
            "--output-dir",
            str(tmp_path),
            "--pdf",
            "--dispatch-telegram",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["issue"]["issue_id"] == "26068"
    assert len(payload["recommendations"]) == 14
    assert payload["recommendations"][0]["pick"] == "31"
    assert payload["artifacts"]["pdf_path"].endswith(".pdf")
    assert payload["dispatch"]["status"] == "dry_run"
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")



def test_zucai_renjiu_daily_command_generates_three_tiers(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-renjiu-daily",
            "--date",
            "2026-04-26",
            "--issue-file",
            "nutmeg/zucai/samples/26068-issue.json",
            "--odds-file",
            "nutmeg/zucai/samples/26068-odds.json",
            "--output-dir",
            str(tmp_path),
            "--pdf",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["recommended_ticket_id"] == "main"
    assert [ticket["ticket_id"] for ticket in payload["tickets"]] == [
        "conservative",
        "main",
        "aggressive",
    ]
    assert payload["artifacts"]["pdf_path"].endswith("analysis.pdf")
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")

def test_zucai_report_command_rejects_invalid_issue(tmp_path) -> None:
    issue_file = tmp_path / "bad-issue.json"
    issue_file.write_text(
        json.dumps(
            {"issue_id": "bad", "matches": [{"match_no": 1, "home_team": "A", "away_team": "B"}]}
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["zucai-report", "--issue-file", str(issue_file), "--format", "json"],
    )

    assert result.exit_code == 2
    assert "exactly 14" in result.stdout


def test_zucai_grade_command_returns_plan_coverage(tmp_path) -> None:
    report_result = runner.invoke(
        app,
        [
            "zucai-report",
            "--issue-id",
            "26068",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    assert report_result.exit_code == 0
    report_payload = json.loads(report_result.stdout)

    grade_result = runner.invoke(
        app,
        [
            "zucai-grade",
            "--report-file",
            report_payload["artifacts"]["report_json_path"],
            "--outcomes-file",
            "nutmeg/zucai/samples/26068-outcomes.json",
            "--format",
            "json",
        ],
    )

    assert grade_result.exit_code == 0
    payload = json.loads(grade_result.stdout)
    assert payload["issue_id"] == "26068"
    assert len(payload["match_results"]) == 14
    assert any(plan["covered"] for plan in payload["plan_results"])


def test_zucai_auto_run_command_skips_no_issue(tmp_path) -> None:
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps({"entries": []}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "zucai-auto-run",
            "--date",
            "2026-04-27",
            "--slot",
            "afternoon",
            "--registry-file",
            str(registry_file),
            "--output-dir",
            str(tmp_path / "scheduled"),
            "--run-record-file",
            str(tmp_path / "records.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "skipped_no_issue"
    assert payload["dispatch"]["status"] == "skipped"
    assert payload["artifacts"]["pdf_path"] is None
    assert not (tmp_path / "records.json").exists()


def test_zucai_auto_run_command_generates_afternoon_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    result = runner.invoke(
        app,
        [
            "zucai-auto-run",
            "--date",
            "2026-04-26",
            "--slot",
            "afternoon",
            "--registry-file",
            "nutmeg/zucai/samples/scheduled-issues.json",
            "--output-dir",
            str(tmp_path / "scheduled"),
            "--run-record-file",
            str(tmp_path / "records.json"),
            "--dispatch-telegram",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert payload["issue_id"] == "26068"
    assert payload["slot_label"] == "16:00首版分析"
    assert payload["dispatch"]["status"] == "dry_run"
    assert "16:00首版分析" in payload["dispatch"]["caption"]
    assert payload["artifacts"]["pdf_path"].endswith(".pdf")
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert records[0]["slot"] == "afternoon"


def test_zucai_auto_run_command_duplicate_and_force(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    base_args = [
        "zucai-auto-run",
        "--date",
        "2026-04-26",
        "--slot",
        "revision",
        "--registry-file",
        "nutmeg/zucai/samples/scheduled-issues.json",
        "--output-dir",
        str(tmp_path / "scheduled"),
        "--run-record-file",
        str(tmp_path / "records.json"),
        "--dispatch-telegram",
        "--dry-run",
        "--format",
        "json",
    ]

    first = runner.invoke(app, base_args)
    duplicate = runner.invoke(app, base_args)
    forced = runner.invoke(app, [*base_args, "--force"])

    assert first.exit_code == 0
    assert duplicate.exit_code == 0
    assert forced.exit_code == 0
    assert json.loads(first.stdout)["status"] == "dry_run"
    assert json.loads(duplicate.stdout)["status"] == "skipped_duplicate"
    assert json.loads(forced.stdout)["status"] == "dry_run"
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert len(records) == 2


def test_zucai_source_sync_command_generates_registry(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-source-sync",
            "--source-file",
            "nutmeg/zucai/samples/26068-source-notice.html",
            "--date",
            "2026-04-26",
            "--output-dir",
            str(tmp_path / "zucai"),
            "--registry-file",
            str(tmp_path / "zucai" / "issues.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["parsed_count"] == 1
    assert payload["active_issue_ids"] == ["26068"]
    assert Path(payload["written_issue_paths"]["26068"]).exists()
    registry = json.loads(Path(payload["registry_path"]).read_text(encoding="utf-8"))
    assert registry["entries"][0]["issue_id"] == "26068"


def test_zucai_source_sync_command_rejects_url_without_live_fetch(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-source-sync",
            "--source-url",
            "https://example.test/source.html",
            "--date",
            "2026-04-26",
            "--output-dir",
            str(tmp_path / "zucai"),
            "--registry-file",
            str(tmp_path / "zucai" / "issues.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    assert "requires --live-fetch" in result.stdout


def test_jczq_debate_init_command_creates_workspace(tmp_path) -> None:
    run_dir = tmp_path / "daily" / "2026-05-06"
    run_dir.mkdir(parents=True)
    (run_dir / "brief.md").write_text("# brief\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "jczq-debate-init",
            "--date",
            "2026-05-06",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run_date"] == "2026-05-06"
    assert Path(payload["artifacts"]["shared_brief_path"]).exists()
    assert Path(payload["artifacts"]["gpt_analysis_path"]).exists()


def test_jczq_mixed_report_live_is_retired_with_daily_workflow_guidance() -> None:
    result = runner.invoke(app, ["jczq-mixed-report", "--provider", "live", "--format", "json"])

    assert result.exit_code == 2
    assert "retired" in result.stdout
    assert "jczq-daily-brief" in result.stdout


def test_jczq_second_leg_date_today_resolves_to_calendar_date(monkeypatch, tmp_path) -> None:
    import nutmeg.services.jczq_second_leg as second_leg

    seen: dict[str, object] = {}

    def fake_suggest_second_legs(**kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setattr(second_leg, "suggest_second_legs", fake_suggest_second_legs)

    result = runner.invoke(
        app,
        [
            "jczq-second-leg",
            "--date",
            "today",
            "--output-dir",
            str(tmp_path),
            "--auto",
        ],
    )

    assert result.exit_code == 0
    assert seen["run_date"] == date.today().isoformat()
    assert seen["output_dir"] == tmp_path
    assert "ok" in result.stdout


def test_jczq_debate_compare_command_returns_conflicts(tmp_path) -> None:
    run_dir = tmp_path / "daily" / "2026-05-06"
    debate_dir = run_dir / "debate"
    debate_dir.mkdir(parents=True)
    (debate_dir / "gpt-analysis.md").write_text(
        "`周三003比分0:0@11 × 周三007胜@1.53`",
        encoding="utf-8",
    )
    (debate_dir / "claude-analysis.md").write_text(
        "`周三003比分0:0@11 × 周三007平@3.9`",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "jczq-debate-compare",
            "--date",
            "2026-05-06",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "周三003比分0:0" in payload["consensus_legs"]
    assert payload["conflict_matches"] == ["周三007"]
    assert (debate_dir / "disagreements.md").exists()


def test_jczq_debate_finalize_command_writes_final_plan(tmp_path) -> None:
    run_dir = tmp_path / "daily" / "2026-05-06"
    debate_dir = run_dir / "debate"
    debate_dir.mkdir(parents=True)
    (debate_dir / "human-notes.md").write_text("## 最终票\n`周三003比分0:0@11`", encoding="utf-8")
    (debate_dir / "disagreements.md").write_text("## 共同认可\n- 周三003比分0:0", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "jczq-debate-finalize",
            "--date",
            "2026-05-06",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "finalized"
    assert Path(payload["final_plan_path"]).exists()


def test_jczq_daily_brief_degrades_gracefully_without_api_key(
    monkeypatch, tmp_path: Path
) -> None:
    # The brief defaults to the 500.com odds source — quota-free, no
    # NUTMEG_API_FOOTBALL_KEY needed. When the 500.com collector cannot reach
    # the site (offline test env, simulated here by an empty collection) the
    # bridge degrades honestly: every match is marked "无 500.com 数据" and the
    # brief still renders the 赔率冲突点 section end-to-end, exit 0.
    from nutmeg.data import fcom500 as fcom500_module
    from nutmeg.services.jczq_daily import JczqDailyAdvisorService
    from tests.test_jczq_daily_service import FakeProvider

    monkeypatch.setenv("NUTMEG_API_FOOTBALL_KEY", "")
    # Never touch the live 500.com site: simulate an unreachable collector.
    monkeypatch.setattr(
        fcom500_module.Fcom500OddsProvider,
        "collect",
        lambda self, run_date: {},
    )
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    result = runner.invoke(
        app,
        [
            "jczq-daily-brief",
            "--replay",
            "2026-05-01",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    # The 赔率冲突点 section renders from the (degraded) value engine — not the
    # unwired placeholder, since the 500.com path needs no API key.
    assert "## 赔率冲突点" in result.stdout
    assert "无 500.com 数据" in result.stdout


def test_brief_value_bridge_defaults_to_fcom500(monkeypatch) -> None:
    """The daily brief's value bridge defaults to the 500.com odds source —
    ``_build_jczq_value_bridge_for_brief`` passes ``use_fcom500=True`` so the
    conflict engine runs quota-free with no API-Football key."""
    import nutmeg.interfaces.cli as cli_module
    from nutmeg.services import jczq_value_wiring

    captured: dict[str, object] = {}

    def fake_build(*, settings, run_date, value_service_factory, use_fcom500=False):
        captured["use_fcom500"] = use_fcom500
        captured["run_date"] = run_date
        return "bridge-sentinel"

    monkeypatch.setattr(jczq_value_wiring, "build_jczq_value_bridge", fake_build)

    bridge = cli_module._build_jczq_value_bridge_for_brief("2026-05-17")

    assert bridge == "bridge-sentinel"
    assert captured["use_fcom500"] is True
    assert captured["run_date"] == "2026-05-17"


def test_jczq_bold_combos_replay_renders_honest_label(
    monkeypatch, tmp_path: Path
) -> None:
    """`jczq-bold-combos --replay <date>` replays a stored context.json through
    the entertainment-purpose bold-combo engine: exit 0 and the welded 🎲
    honest label is present (spec §7)."""
    from nutmeg.data import fcom500 as fcom500_module
    from nutmeg.services.jczq_bold_combos import HARD_LABEL
    from nutmeg.services.jczq_daily import JczqDailyAdvisorService
    from tests.test_jczq_daily_service import FakeProvider

    # Never touch the live 500.com site — simulate an unreachable collector so
    # the engine runs on 体彩 odds alone (graceful 欧赔 degradation).
    monkeypatch.setattr(
        fcom500_module.Fcom500OddsProvider,
        "collect",
        lambda self, run_date: {},
    )
    JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    result = runner.invoke(
        app,
        [
            "jczq-bold-combos",
            "--replay",
            "2026-05-01",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert HARD_LABEL in result.stdout
    assert "大盘面混乱值" in result.stdout
    # No advantage wording leaked into the rendered CLI output.
    body = result.stdout[result.stdout.index(HARD_LABEL) + len(HARD_LABEL):]
    for word in ("胜率", "+EV", "正期望", "推荐下注", "重仓"):
        assert word not in body


def test_jczq_bold_combos_replay_renders_multi_market(tmp_path, monkeypatch) -> None:
    """A --replay run off a persisted Sporttery snapshot renders the welded
    label and contains no advantage wording."""
    import json

    from nutmeg.services.jczq_bold_combos import HARD_LABEL

    # persist a 3-match snapshot so the engine can build a 3-fold
    def m(no: str, home: str) -> dict:
        return {
            "matchNumStr": no, "businessDate": "2026-05-18",
            "matchStatus": "Selling", "leagueAbbName": "芬超",
            "homeTeamAbbName": home, "awayTeamAbbName": "客",
            "had": {"h": "2.00", "d": "3.20", "a": "3.50"},
            "hhad": {"h": "3.10", "d": "3.30", "a": "2.10", "goalLine": "-1"},
            "ttg": {f"s{k}": str(4.0 + k) for k in range(8)},
            "crs": {"s01s00": "6.50", "s00s00": "9.00", "s03s02": "41.0"},
        }
    snap_dir = tmp_path / "daily" / "2026-05-18"
    snap_dir.mkdir(parents=True)
    (snap_dir / "sporttery_markets.json").write_text(
        json.dumps({"matchInfoList": [{"businessDate": "2026-05-18",
            "subMatchList": [m("周一001", "A"), m("周一002", "B"), m("周一003", "C")]}]}),
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "jczq-bold-combos", "--replay", "2026-05-18",
        "--output-dir", str(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    assert result.output.startswith(HARD_LABEL)
    for banned in ("胜率", "edge", "+EV", "正期望", "推荐下注", "重仓"):
        # the label's own legitimate "非 edge" negation is on the first line
        body = "\n".join(result.output.splitlines()[1:])
        assert banned not in body, f"banned word leaked: {banned}"


def test_jczq_web_command_starts_localhost_app(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(app_object, *, host: str, port: int) -> None:
        calls.append({"app": app_object, "host": host, "port": port})

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(
        app,
        [
            "jczq-web",
            "--output-dir",
            str(tmp_path),
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
    )

    assert result.exit_code == 0
    assert calls
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8765
    assert calls[0]["app"].title == "Nutmeg JCZQ Cockpit"
