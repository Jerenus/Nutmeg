"""Foundation CLI commands: doctor, fixtures, sync, reference, snapshot.

Command functions live here and register on the shared
``nutmeg.interfaces.cli.app`` via ``@_cli.app.command()``. Every CLI-package
global (factories, helpers, options, re-exported imports) is reached through
``_cli`` so behaviour — including test monkeypatches on the ``cli`` package —
is identical to the pre-split single-module layout.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli


@_cli.app.command()
def doctor(format: str = _cli.typer.Option("text", "--format", help="text or json")) -> None:
    settings = _cli.get_settings()
    _cli.ensure_storage_paths(settings)
    _cli.create_analytics_schema(settings)
    bridge = _cli.inspect_superpowers_bridge(_cli.Path.cwd())
    harness = _cli.inspect_harness(_cli.Path.cwd())
    trace_context = _cli.build_trace_context(settings, settings.default_user_id)
    session = _cli._build_state_session()
    try:
        latest_sync = _cli.SqlAlchemySyncRunRepository(session).latest()
    finally:
        session.close()
    report = {
        "app": {
            "name": settings.app_name,
            "env": settings.app_env,
            "default_user_id": settings.default_user_id,
        },
        "storage": {
            "data_dir": str(settings.data_dir),
            "state_db_url": settings.state_db_url,
            "analytics_db_url": settings.analytics_db_url,
        },
        "providers": {
            "api_football_configured": bool(settings.api_football_key),
            "portkey_configured": bool(settings.portkey_api_key),
            "openai_configured": bool(settings.openai_api_key),
            "agent_synthesis_enabled": settings.agent_synthesis_enabled,
            "agent_synthesis_configured": bool(
                settings.agent_synthesis_enabled and settings.portkey_api_key
            ),
            "agent_synthesis_model": settings.anthropic_model,
            "bot_llm_fallback_enabled": settings.bot_llm_fallback_enabled,
            "bot_llm_fallback_configured": bool(
                settings.bot_llm_fallback_enabled and settings.openai_api_key
            ),
            "bot_llm_fallback_model": settings.bot_llm_fallback_model,
            "langsmith_enabled": trace_context.enabled,
            "langsmith_project": trace_context.project,
        },
        "workflow": bridge.to_dict(),
        "harness": harness.to_dict(),
        "latest_sync": _cli.asdict(latest_sync) if latest_sync else None,
    }
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(report, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"[bold]Nutmeg[/bold] env={settings.app_env} user={settings.default_user_id}"
    )
    _cli.console.print(f"state={settings.state_db_url}")
    _cli.console.print(f"analytics={settings.analytics_db_url}")
    _cli.console.print(
        "providers: "
        f"api-football={'yes' if settings.api_football_key else 'no'}, "
        f"portkey={'yes' if settings.portkey_api_key else 'no'}, "
        f"openai={'yes' if settings.openai_api_key else 'no'}, "
        f"agent-synthesis={'yes' if settings.agent_synthesis_enabled else 'no'}, "
        f"bot-fallback={'yes' if settings.bot_llm_fallback_enabled else 'no'}, "
        f"langsmith={'yes' if trace_context.enabled else 'no'}"
    )
    _cli.console.print(f"superpowers bridge verdict={bridge.verdict}")
    _cli.console.print(
        f"harness: {harness.passing_features}/{harness.total_features} feature checks passing"
    )
    if latest_sync is not None:
        _cli.console.print(
            "latest sync: "
            f"status={latest_sync.status} fixtures={latest_sync.fixtures_written} "
            f"requests={latest_sync.requests_made} scope={latest_sync.scope}"
        )


@_cli.app.command()
def fixtures(
    league: str = _cli.typer.Option("epl", "--league"),
    next_days: int = _cli.typer.Option(7, "--next"),
    demo: bool = _cli.typer.Option(False, "--demo", help="use in-memory demo fixtures"),
) -> None:
    settings = _cli.get_settings()
    fixture_service, session = _cli.build_fixture_service()
    try:
        with _cli.traced_operation(
            settings,
            operation_name="cli.fixtures.list",
            user_id=settings.default_user_id,
            tags=["fixtures", "list"],
            metadata={"league": league, "days": next_days, "demo": demo},
        ):
            fixtures = fixture_service.list_upcoming(league, next_days, demo=demo)
    finally:
        session.close()

    if not fixtures:
        _cli.console.print(
            "No fixtures available yet. Run `nutmeg fixtures-sync` or `nutmeg seed-demo`."
        )
        raise _cli.typer.Exit(code=0)

    _cli.console.print(f"Upcoming fixtures: {league}")
    for fixture in fixtures:
        _cli.console.print(
            " | ".join(
                [
                    fixture.fixture_id,
                    fixture.kickoff_at.isoformat(),
                    f"{fixture.home_team} vs {fixture.away_team}",
                    fixture.status_short,
                    fixture.venue or "-",
                ]
            )
        )


@_cli.app.command("fixtures-sync")
def fixtures_sync(
    league: list[str] | None = _cli.LEAGUE_FILTER_OPTION,
    days: int | None = _cli.DAYS_OPTION,
    timezone: str | None = _cli.TIMEZONE_OPTION,
    past_days: int = _cli.typer.Option(0, "--past-days"),
) -> None:
    settings = _cli.get_settings()
    requested_days = days or settings.default_sync_days
    requested_timezone = timezone or settings.sync_timezone
    sync_service, session = _cli.build_sync_service()
    try:
        with _cli.traced_operation(
            settings,
            operation_name="cli.fixtures.sync",
            user_id=settings.default_user_id,
            tags=["fixtures", "sync"],
            metadata={
                "league_codes": league or ["all"],
                "days": requested_days,
                "past_days": past_days,
                "timezone": requested_timezone,
            },
        ):
            report = sync_service.sync(
                league_codes=league,
                days=requested_days,
                past_days=past_days,
                timezone=requested_timezone,
            )
            session.commit()
    except _cli.ApiFootballError as exc:
        session.commit()
        _cli.console.print(f"API-Football sync failed: {exc}")
        raise _cli.typer.Exit(code=2) from exc
    except Exception:
        session.commit()
        raise
    finally:
        session.close()

    _cli.console.print(
        f"Synced {report.total_fixtures} fixtures across {len(report.leagues)} competition(s)."
    )
    for summary in report.leagues:
        _cli.console.print(
            " - ".join(
                [
                    summary.league_code,
                    f"season={summary.season}",
                    f"fixtures={summary.fixtures_written}",
                    f"requests={summary.requests_made}",
                ]
            )
        )


@_cli.app.command("seed-demo")
def seed_demo(league: str = _cli.typer.Option("epl", "--league")) -> None:
    settings = _cli.get_settings()
    fixture_service, session = _cli.build_fixture_service()
    try:
        with _cli.traced_operation(
            settings,
            operation_name="cli.fixtures.seed_demo",
            user_id=settings.default_user_id,
            tags=["fixtures", "demo"],
            metadata={"league": league},
        ):
            fixtures = fixture_service.seed_demo(league)
            session.commit()
    finally:
        session.close()
    _cli.console.print(f"Seeded {len(fixtures)} fixtures for {league}.")


@_cli.app.command("reference-refresh")
def reference_refresh(
    league: str = _cli.typer.Option("epl", "--league"),
    season: int = _cli.typer.Option(..., "--season"),
) -> None:
    settings = _cli.get_settings()
    materialization_service, session = _cli.build_materialization_service()
    try:
        with _cli.traced_operation(
            settings,
            operation_name="cli.reference.refresh",
            user_id=settings.default_user_id,
            tags=["reference", "materialization"],
            metadata={"league": league, "season": season},
        ):
            result = materialization_service.refresh_snapshot_support_data(league, season)
            if session is not None:
                session.commit()
    finally:
        if session is not None:
            session.close()
    _cli.console.print(
        f"{result.league_code} season={result.season} "
        f"transfermarkt_rows={result.transfermarkt_rows} "
        f"soccerdata_rows={result.soccerdata_rows}"
    )


@_cli.app.command("fixture-snapshot")
def fixture_snapshot(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    recent_matches: int = _cli.typer.Option(5, "--recent-matches"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    snapshot_service, session = _cli.build_snapshot_service()
    captured_stdout = _cli.io.StringIO()
    root_logger = _cli.logging.getLogger("root")
    original_root_level = root_logger.level
    suppress_root_info = format == "json" and (
        original_root_level == _cli.logging.NOTSET or original_root_level < _cli.logging.WARNING
    )
    try:
        if suppress_root_info:
            root_logger.setLevel(_cli.logging.WARNING)
        with _cli.redirect_stdout(captured_stdout):
            with _cli.traced_operation(
                settings,
                operation_name="cli.fixtures.snapshot",
                user_id=settings.default_user_id,
                tags=["fixtures", "snapshot"],
                metadata={
                    "fixture_id": fixture_id,
                    "recent_matches": recent_matches,
                    "format": format,
                },
            ):
                snapshot = snapshot_service.build_snapshot(
                    fixture_id,
                    recent_matches=recent_matches,
                )
    except (_cli.FixtureNotFoundError, _cli.SoccerDataError) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    finally:
        if suppress_root_info:
            root_logger.setLevel(original_root_level)
        session.close()

    noisy_stdout = captured_stdout.getvalue()
    if noisy_stdout:
        print(noisy_stdout, file=_cli.sys.stderr, end="")

    payload = _cli.asdict(snapshot)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"{snapshot.fixture.fixture_id} | {snapshot.fixture.kickoff_at.isoformat()} | "
        f"{snapshot.fixture.home_team} vs {snapshot.fixture.away_team}"
    )
    if snapshot.environment is not None:
        weather_summary = "weather=n/a"
        if snapshot.environment.weather is not None:
            weather_summary = (
                f"weather={snapshot.environment.weather.temperature_c}C "
                f"precip={snapshot.environment.weather.precipitation_probability} "
                f"wind={snapshot.environment.weather.wind_speed_kph}"
            )
        travel_summary = "travel=n/a"
        if snapshot.environment.away_travel is not None:
            travel_summary = (
                f"travel={snapshot.environment.away_travel.distance_km}km "
                f"({snapshot.environment.away_travel.bucket})"
            )
        kickoff_local = (
            snapshot.environment.kickoff_local_time.isoformat()
            if snapshot.environment.kickoff_local_time is not None
            else "n/a"
        )
        _cli.console.print(
            "environment "
            f"venue={snapshot.environment.venue_name or '-'} "
            f"referee={snapshot.environment.referee or '-'} "
            f"kickoff_local={kickoff_local} "
            f"{weather_summary} {travel_summary}"
        )
    for side, team in [("home", snapshot.home), ("away", snapshot.away)]:
        _cli.console.print(f"{side}: {team.canonical_name}")
        if team.season_metrics is not None:
            shots = (
                f"{team.season_metrics.shots:.1f}"
                if team.season_metrics.shots is not None
                else "n/a"
            )
            shots_on_target = (
                f"{team.season_metrics.shots_on_target:.1f}"
                if team.season_metrics.shots_on_target is not None
                else "n/a"
            )
            goals = (
                f"{team.season_metrics.goals:.1f}"
                if team.season_metrics.goals is not None
                else "n/a"
            )
            xg = f"{team.season_metrics.xg:.1f}" if team.season_metrics.xg is not None else "n/a"
            _cli.console.print(
                f"  season shots={shots} sot={shots_on_target} goals={goals} xg={xg}"
            )
        if team.recent_form is not None:
            _cli.console.print(
                f"  recent W-D-L={team.recent_form.wins}-{team.recent_form.draws}-"
                f"{team.recent_form.losses} points={team.recent_form.points} "
                f"xg={team.recent_form.xg_for:.1f}/{team.recent_form.xg_against:.1f}"
            )
        if team.shot_summary is not None:
            _cli.console.print(
                f"  shots count={team.shot_summary.shots} goals={team.shot_summary.goals} "
                f"open_play={team.shot_summary.open_play_shots} "
                f"xg={team.shot_summary.total_xg:.2f}"
            )
        if team.market_value is not None:
            _cli.console.print(
                f"  market value={team.market_value.total_market_value_eur} "
                f"source={team.market_value.source}"
            )
        if team.injuries:
            injury_summary = ", ".join(
                f"{injury.player_name} ({injury.reason or injury.status})"
                for injury in team.injuries
            )
            _cli.console.print("  injuries=" + injury_summary)
        if team.lineup is not None:
            _cli.console.print(
                f"  lineup status={team.lineup.status} formation={team.lineup.formation or '-'} "
                f"players={', '.join(player.player_name for player in team.lineup.players[:11])}"
            )
        if team.availability is not None:
            _cli.console.print(
                "  availability "
                f"injuries={len(team.availability.injuries)} "
                f"suspensions={len(team.availability.suspensions)} "
                f"returning={len(team.availability.returning_players)} "
                f"summary={team.availability.expected_absences_summary or '-'}"
            )
            if team.availability.bench_depth is not None:
                _cli.console.print(
                    "  bench depth "
                    f"label={team.availability.bench_depth.label} "
                    f"available={team.availability.bench_depth.available_players} "
                    f"value={team.availability.bench_depth.bench_market_value_eur}"
                )
    if snapshot.matchup is not None:
        h2h_matches = (
            snapshot.matchup.head_to_head.matches if snapshot.matchup.head_to_head else "n/a"
        )
        home_trend = "n/a"
        if snapshot.matchup.home_trend is not None:
            home_trend = (
                f"{snapshot.matchup.home_trend.goals_for_per_match:.2f}/"
                f"{snapshot.matchup.home_trend.xg_for_per_match:.2f}"
            )
        away_trend = "n/a"
        if snapshot.matchup.away_trend is not None:
            away_trend = (
                f"{snapshot.matchup.away_trend.goals_for_per_match:.2f}/"
                f"{snapshot.matchup.away_trend.xg_for_per_match:.2f}"
            )
        _cli.console.print(
            f"matchup h2h={h2h_matches} home_trend={home_trend} away_trend={away_trend}"
        )
    _cli.console.print(f"deferred: {', '.join(snapshot.deferred_sections)}")


@_cli.app.command("classify-query")
def classify_query(query: str) -> None:
    _cli.console.print(_cli.classify_intent(query).value)
