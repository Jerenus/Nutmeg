"""Odds, value-board, and prediction CLI commands.

Command functions live here and register on the shared
``nutmeg.interfaces.cli.app`` via ``@_cli.app.command()``. Every CLI-package
global (factories, helpers, options, re-exported imports) is reached through
``_cli`` so behaviour — including test monkeypatches on the ``cli`` package —
is identical to the pre-split single-module layout.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli


@_cli.app.command("odds-snapshot")
def odds_snapshot(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    odds_service, session = _cli.build_odds_service()
    try:
        with _cli.traced_operation(
            settings,
            operation_name="cli.odds.snapshot",
            user_id=settings.default_user_id,
            tags=["odds", "snapshot"],
            metadata={"fixture_id": fixture_id, "format": format},
        ):
            snapshot = odds_service.build_snapshot(fixture_id)
    except (
        _cli.OddsFixtureNotFoundError,
        _cli.ApiFootballError,
        _cli.TheOddsApiError,
        ValueError,
    ) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = _cli.asdict(snapshot)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    updated_at = snapshot.provider.updated_at.isoformat() if snapshot.provider.updated_at else "n/a"
    _cli.console.print(
        f"{snapshot.fixture.fixture_id} | {snapshot.fixture.kickoff_at.isoformat()} | "
        f"{snapshot.fixture.home_team} vs {snapshot.fixture.away_team}"
    )
    _cli.console.print(
        "provider "
        f"name={snapshot.provider.name} "
        f"updated={updated_at} "
        f"bookmakers={snapshot.provider.bookmaker_count}"
    )
    for market_key, market in snapshot.markets.items():
        line = f" line={market.line}" if market.line is not None else ""
        _cli.console.print(
            f"{market_key} status={market.status}{line} source_ids={market.source_market_ids}"
        )
        for outcome in market.outcomes:
            fair_probability = (
                f"{outcome.fair_probability:.4f}" if outcome.fair_probability is not None else "n/a"
            )
            fair_price = f"{outcome.fair_odds:.3f}" if outcome.fair_odds is not None else "n/a"
            _cli.console.print(
                f"  {outcome.outcome_key} best={outcome.best_odds} "
                f"avg={outcome.average_odds} fair_prob={fair_probability} "
                f"fair_odds={fair_price} books={outcome.bookmaker_count}"
            )
        if snapshot.history and market_key in snapshot.history:
            history = snapshot.history[market_key]
            if history.points:
                _cli.console.print(
                    f"  history points={len(history.points)} "
                    f"movement={history.movement or 'n/a'} "
                    f"span={history.movement_span if history.movement_span is not None else 'n/a'} "
                    f"drift={history.drift_vs_current or {}}"
                )


@_cli.app.command("value-board")
def value_board(
    league: str = _cli.typer.Option("epl", "--league"),
    days: int = _cli.typer.Option(3, "--days"),
    limit: int = _cli.typer.Option(10, "--limit"),
    min_edge: float = _cli.typer.Option(0.03, "--min-edge"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_value_board_service()
    try:
        board = service.build_board(
            league=league,
            days=days,
            limit=limit,
            min_edge=min_edge,
        )
    except (_cli.ApiFootballError, _cli.TheOddsApiError, ValueError) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = _cli.asdict(board)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"Value board: league={board.league} days={board.days} "
        f"candidates={len(board.candidates)} skipped={len(board.skipped)}"
    )
    if not board.candidates:
        _cli.console.print("No positive model-vs-market edges found.")
    for candidate in board.candidates:
        _cli.console.print(
            " | ".join(
                [
                    candidate.fixture_id,
                    candidate.kickoff_at.isoformat(),
                    f"{candidate.home_team} vs {candidate.away_team}",
                    candidate.outcome_key,
                    f"edge={candidate.edge:.1%}",
                    f"model={candidate.model_probability:.1%}",
                    f"market={candidate.market_probability:.1%}",
                    f"best={candidate.best_odds:.3f}",
                    f"kelly25={candidate.quarter_kelly_fraction:.2%}",
                    f"rating={candidate.rating}",
                ]
            )
        )
    if board.skipped:
        _cli.console.print("Skipped fixtures:")
        for skipped in board.skipped[:5]:
            _cli.console.print(f" - {skipped.fixture_id}: {skipped.reason}")


@_cli.app.command("player-profile")
def player_profile(
    player: str = _cli.typer.Option(..., "--player"),
    team: str = _cli.typer.Option(..., "--team"),
    league: str = _cli.typer.Option("epl", "--league"),
    season: int | None = _cli.typer.Option(None, "--season"),
    similar_limit: int = _cli.typer.Option(5, "--similar-limit"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_player_profile_service()
    try:
        profile = service.build_profile(
            league=league,
            season=season,
            team=team,
            player=player,
            similar_limit=similar_limit,
        )
    finally:
        session.close()

    payload = _cli.asdict(profile)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    identity_name = profile.identity.canonical_name if profile.identity else player
    _cli.console.print(
        f"Player profile: {identity_name} | team={profile.query_team} "
        f"league={profile.league} season={profile.season}"
    )
    if profile.market:
        market_value = (
            profile.market.market_value_eur
            if profile.market.market_value_eur is not None
            else "n/a"
        )
        _cli.console.print(
            f"market position={profile.market.position or 'n/a'} "
            f"value={market_value} "
            f"source={profile.market.source}"
        )
    if profile.season_metrics:
        metrics = profile.season_metrics
        _cli.console.print(
            f"season minutes={metrics.minutes} goals90={metrics.goals_per90} "
            f"assists90={metrics.assists_per90} xg90={metrics.xg_per90} "
            f"xa90={metrics.xa_per90}"
        )
    if profile.availability:
        _cli.console.print(
            f"availability status={profile.availability.status} "
            f"reason={profile.availability.reason or 'n/a'} "
            f"return={profile.availability.expected_return or 'n/a'}"
        )
    if profile.similar_players:
        _cli.console.print("similar players:")
        for item in profile.similar_players:
            _cli.console.print(
                f" - {item.player_name} | {item.team_name} | score={item.similarity_score:.3f}"
            )
    if profile.unavailable_sections:
        _cli.console.print(f"unavailable: {', '.join(profile.unavailable_sections)}")


@_cli.app.command("eval-run")
def eval_run(
    dataset: str = _cli.typer.Option("starter", "--dataset"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_eval_service()
    try:
        result = service.run_dataset(dataset)
    except _cli.EvalDatasetNotFoundError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = _cli.asdict(result)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"eval dataset={result.dataset} total={result.total_cases} "
        f"passed={result.passed_cases} failed={result.failed_cases}"
    )
    for item in result.results:
        status = "PASS" if item.passed else "FAIL"
        missing = f" missing={item.missing_keywords}" if item.missing_keywords else ""
        _cli.console.print(f" - {item.case_id} [{item.category}] {status}{missing}")


@_cli.app.command("prediction-record")
def prediction_record(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    league: str = _cli.typer.Option("epl", "--league"),
    home_team: str = _cli.typer.Option(..., "--home-team"),
    away_team: str = _cli.typer.Option(..., "--away-team"),
    home_probability: float = _cli.typer.Option(..., "--home-probability"),
    draw_probability: float = _cli.typer.Option(..., "--draw-probability"),
    away_probability: float = _cli.typer.Option(..., "--away-probability"),
    picked_outcome: str = _cli.typer.Option(..., "--pick", help="home, draw, or away"),
    notes: str | None = _cli.typer.Option(None, "--notes"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    repository, session = _cli.build_prediction_repository()
    try:
        prediction_id = repository.record_prediction(
            user_id=settings.default_user_id,
            fixture_id=fixture_id,
            league=league,
            home_team=home_team,
            away_team=away_team,
            probabilities={
                "home": home_probability,
                "draw": draw_probability,
                "away": away_probability,
            },
            picked_outcome=picked_outcome,
            notes=notes,
        )
    except ValueError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = {"prediction_id": prediction_id, "status": "recorded"}
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(f"Recorded prediction id={prediction_id}")


@_cli.app.command("prediction-outcome")
def prediction_outcome(
    prediction_id: int = _cli.typer.Option(..., "--prediction-id"),
    actual_outcome: str = _cli.typer.Option(..., "--actual", help="home, draw, or away"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    repository, session = _cli.build_prediction_repository()
    try:
        repository.record_outcome(
            prediction_id=prediction_id,
            actual_outcome=actual_outcome,
        )
    except (_cli.PredictionNotFoundError, ValueError) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = {
        "prediction_id": prediction_id,
        "actual_outcome": actual_outcome,
        "status": "resolved",
    }
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(f"Recorded outcome id={prediction_id} actual={actual_outcome}")


@_cli.app.command("prediction-review")
def prediction_review(
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    repository, session = _cli.build_prediction_repository()
    try:
        summary = repository.review(user_id=settings.default_user_id)
    finally:
        session.close()

    payload = _cli.asdict(summary)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    brier = summary.average_brier_score if summary.average_brier_score is not None else "n/a"
    accuracy = summary.pick_accuracy if summary.pick_accuracy is not None else "n/a"
    _cli.console.print(
        f"prediction review total={summary.total_predictions} "
        f"resolved={summary.resolved_predictions} "
        f"brier={brier} "
        f"accuracy={accuracy}"
    )
