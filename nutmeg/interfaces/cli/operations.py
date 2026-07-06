"""Daily-operations, agent, and match-brief CLI commands.

Command functions live here and register on the shared
``nutmeg.interfaces.cli.app`` via ``@_cli.app.command()``. Every CLI-package
global (factories, helpers, options, re-exported imports) is reached through
``_cli`` so behaviour — including test monkeypatches on the ``cli`` package —
is identical to the pre-split single-module layout.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli


@_cli.app.command("daily-run")
def daily_run(
    league: str = _cli.typer.Option("epl", "--league"),
    days: int = _cli.typer.Option(3, "--days"),
    limit: int = _cli.typer.Option(5, "--limit"),
    query: str = _cli.typer.Option("Give me the pre-match operator brief.", "--query"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    live_sync: bool = _cli.typer.Option(False, "--live-sync"),
    briefs: bool = _cli.typer.Option(False, "--briefs"),
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_daily_operator_service()
    try:
        summary = service.run(
            league=league,
            days=days,
            limit=limit,
            query=query,
            dry_run=dry_run,
            live_sync=live_sync,
            briefs=briefs,
            dispatch_telegram=dispatch_telegram,
        )
        session.commit()
    except Exception:
        session.commit()
        raise
    finally:
        session.close()

    payload = _cli.asdict(summary)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"daily-run league={summary.league} days={summary.days} "
        f"dry_run={summary.dry_run} live_sync={summary.live_sync}"
    )
    _cli.console.print(
        f"sync status={summary.sync_status} "
        f"fixtures={summary.sync_fixtures_written} requests={summary.sync_requests_made}"
    )
    _cli.console.print(
        f"fixtures considered={summary.fixtures_considered} "
        f"popular={len(summary.popular_matches)} value={len(summary.value_candidates)}"
    )
    _cli.console.print(f"telegram dispatch={summary.telegram_dispatch.status.value}")
    for item in summary.popular_matches:
        _cli.console.print(
            f" - #{item.rank} {item.home_team} vs {item.away_team} "
            f"tier={item.tier} score={item.score}"
        )


@_cli.app.command("tactical-visuals")
def tactical_visuals(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    output_dir: _cli.Path | None = _cli.TACTICAL_OUTPUT_DIR_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_tactical_visual_service()
    try:
        pack = service.build_pack(fixture_id, output_dir=output_dir)
    except (
        _cli.FixtureNotFoundError,
        _cli.ApiFootballError,
        _cli.SoccerDataError,
        ValueError,
    ) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    finally:
        session.close()

    payload = _cli.asdict(pack)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"tactical visuals fixture={pack.fixture.fixture_id} "
        f"artifacts={len(pack.artifacts)} unavailable={pack.unavailable_sections}"
    )
    for artifact in pack.artifacts:
        path = f" path={artifact.path}" if artifact.path else ""
        _cli.console.print(
            f" - {artifact.name} status={artifact.status} source={artifact.source}{path}"
        )
    for insight in pack.insights:
        _cli.console.print(f" insight: {insight}")


@_cli.app.command("event-tactical-models")
def event_tactical_models(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    events_file: _cli.Path | None = _cli.EVENT_DATA_EVENTS_FILE_OPTION,
    output_dir: _cli.Path | None = _cli.TACTICAL_OUTPUT_DIR_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_event_tactical_model_service()
    report = service.build_report(
        fixture_id=fixture_id,
        events_file=events_file,
        output_dir=output_dir,
    )
    payload = report.to_dict()
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    quality = payload["quality"]
    _cli.console.print(
        f"event tactical models fixture={payload['fixture_id']} "
        f"status={quality['status']} events={quality['event_count']}"
    )
    _cli.console.print(
        "models: "
        f"{payload['pass_network']['model_label']}, "
        f"{payload['spatial_value']['model_label']}, "
        f"{payload['player_contributions']['model_label']}"
    )
    if payload["unavailable_sections"]:
        _cli.console.print(f"unavailable={payload['unavailable_sections']}")
    for artifact in payload["artifacts"]:
        path = f" path={artifact['file_path']}" if artifact.get("file_path") else ""
        _cli.console.print(f" - {artifact['title']} kind={artifact['kind']}{path}")
    for warning in payload["warnings"]:
        _cli.console.print(f" warning: {warning}")


@_cli.app.command("fixture-information")
def fixture_information(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    home_team: str | None = _cli.typer.Option(None, "--home-team"),
    away_team: str | None = _cli.typer.Option(None, "--away-team"),
    sources_file: _cli.Path | None = _cli.INFORMATION_SOURCES_FILE_OPTION,
    sources_config: _cli.Path | None = _cli.INFORMATION_SOURCES_CONFIG_OPTION,
    cache_dir: _cli.Path | None = _cli.INFORMATION_CACHE_DIR_OPTION,
    live_fetch: bool = _cli.INFORMATION_LIVE_FETCH_OPTION,
    cache_ttl_seconds: int = _cli.INFORMATION_CACHE_TTL_OPTION,
    timeout_seconds: float = _cli.INFORMATION_TIMEOUT_OPTION,
    max_bytes: int = _cli.INFORMATION_MAX_BYTES_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = (
        _cli.build_live_fixture_information_service(
            manifest_path=sources_config,
            cache_dir=cache_dir,
            live_fetch=live_fetch,
            cache_ttl_seconds=cache_ttl_seconds,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
        if sources_config is not None
        else _cli.build_fixture_information_service()
    )
    digest = service.build_digest(
        fixture_id=fixture_id,
        home_team=home_team,
        away_team=away_team,
        sources_file=None if sources_config is not None else sources_file,
    )
    payload = digest.to_dict()
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"fixture information fixture={payload['fixture_id']} "
        f"status={payload['status']} sources={payload['source_count']}"
    )
    _cli.console.print(str(payload["summary"]))
    for item in payload["items"]:
        _cli.console.print(
            " | ".join(
                [
                    str(item["reliability"]),
                    str(item["source_name"]),
                    str(item["title"]),
                    str(item.get("url") or "-"),
                ]
            )
        )
    for warning in payload["warnings"]:
        _cli.console.print(f" warning: {warning}")


@_cli.app.command("analyze-match")
def analyze_match(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    query: str = _cli.typer.Option(..., "--query"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    analysis_service, session = _cli.build_analysis_service()
    try:
        with _cli.traced_operation(
            settings,
            operation_name="cli.analysis.match",
            user_id=settings.default_user_id,
            tags=["analysis", "match"],
            metadata={"fixture_id": fixture_id, "query": query, "format": format},
        ):
            result = analysis_service.analyze_match(fixture_id, query=query)
    except (
        _cli.InsufficientEvidenceError,
        _cli.FixtureNotFoundError,
        _cli.OddsFixtureNotFoundError,
        _cli.ApiFootballError,
        _cli.TheOddsApiError,
        ValueError,
    ) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    finally:
        if session is not None:
            session.close()

    payload = _cli.asdict(result)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"{result.fixture.fixture_id} | "
        f"{result.fixture.home_team} vs {result.fixture.away_team} | "
        f"intent={result.intent.value}"
    )
    _cli.console.print(f"Judgment: {result.judgment.verdict}")
    _cli.console.print("Core reasons:")
    for reason in result.judgment.core_reasons:
        _cli.console.print(f" - {reason}")
    if result.evidence.tactical_summary:
        _cli.console.print("Tactical evidence:")
        for item in result.evidence.tactical_summary:
            _cli.console.print(f" - {item}")
    if result.evidence.odds_summary:
        _cli.console.print("Market evidence:")
        for item in result.evidence.odds_summary:
            _cli.console.print(f" - {item}")
    if result.evidence.market_shape_summary:
        _cli.console.print("Market shape:")
        for item in result.evidence.market_shape_summary:
            _cli.console.print(f" - {item}")
    if result.evidence.caveats:
        _cli.console.print("Caveats:")
        for item in result.evidence.caveats:
            _cli.console.print(f" - {item}")
    _cli.console.print(f"Conflict state: {result.conflict_state}")
    _cli.console.print(f"Counterargument: {result.judgment.counterargument}")
    _cli.console.print(f"Confidence: {result.judgment.confidence}")


@_cli.app.command("today-briefs")
def today_briefs(
    league: str = _cli.typer.Option("epl", "--league"),
    days: int = _cli.typer.Option(1, "--days"),
    limit: int = _cli.typer.Option(5, "--limit"),
    demo: bool = _cli.typer.Option(False, "--demo"),
    briefs: bool = _cli.typer.Option(False, "--briefs"),
    query: str = _cli.typer.Option("Give me the pre-match operator brief.", "--query"),
    sort: str = _cli.typer.Option("kickoff", "--sort", help="kickoff or popularity"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    fixture_service, fixture_session = _cli.build_fixture_service()
    workflow = None
    workflow_session = None
    try:
        fixtures = fixture_service.list_upcoming(league, days, demo=demo)
        if briefs:
            workflow, workflow_session = _cli.build_agent_workflow()
        payload = _cli.build_today_briefs_payload(
            league=league,
            days=days,
            limit=limit,
            demo=demo,
            briefs=briefs,
            query=query,
            fixtures=fixtures,
            workflow=workflow,
            sort=sort,
        )
    except ValueError as exc:
        if format == "json":
            _cli.typer.echo(_cli.json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        else:
            _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    finally:
        fixture_session.close()
        if workflow_session is not None:
            workflow_session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(f"Today brief candidates: {league}")
    if not payload["items"]:
        _cli.console.print(payload["empty_reason"])
        return
    for item in payload["items"]:
        columns = [
            str(item["fixture_id"]),
            str(item["kickoff_at"]),
            f"{item['home_team']} vs {item['away_team']}",
            str(item.get("venue") or "-"),
            str(item["suggested_bot_message"]),
        ]
        if item.get("popularity"):
            columns.insert(0, f"#{item['rank']} score={item['popularity']['score']}")
        _cli.console.print(" | ".join(columns))
        brief = item.get("brief")
        if isinstance(brief, dict):
            judgment = brief.get("judgment") or {}
            if brief.get("status") == "succeeded":
                _cli.console.print(
                    f"  brief: {judgment.get('verdict')} confidence={judgment.get('confidence')}"
                )
            else:
                _cli.console.print(f"  brief failed: {brief.get('error')}")


@_cli.app.command("popular-matches")
def popular_matches(
    league: str = _cli.typer.Option("epl", "--league"),
    days: int = _cli.typer.Option(1, "--days"),
    limit: int = _cli.typer.Option(5, "--limit"),
    demo: bool = _cli.typer.Option(False, "--demo"),
    query: str = _cli.typer.Option("Give me the pre-match operator brief.", "--query"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    fixture_service, fixture_session = _cli.build_fixture_service()
    try:
        fixtures = fixture_service.list_upcoming(league, days, demo=demo)
        payload = _cli.build_popular_matches_payload(
            league=league,
            days=days,
            limit=limit,
            demo=demo,
            query=query,
            fixtures=fixtures,
        )
    finally:
        fixture_session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(f"Popular matches: {league}")
    if not payload["items"]:
        _cli.console.print(payload["empty_reason"])
        return
    for item in payload["items"]:
        popularity = item["popularity"]
        _cli.console.print(
            " | ".join(
                [
                    f"#{item['rank']}",
                    f"score={popularity['score']}",
                    f"tier={popularity['tier']}",
                    str(item["fixture_id"]),
                    str(item["kickoff_at"]),
                    f"{item['home_team']} vs {item['away_team']}",
                    "; ".join(popularity["reasons"]),
                    str(item["suggested_bot_message"]),
                ]
            )
        )


@_cli.app.command("agent-status")
def agent_status(format: str = _cli.typer.Option("text", "--format", help="text or json")) -> None:
    settings = _cli.get_settings()
    payload = _cli.build_agent_status_payload(settings)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    agent = payload["agent"]
    synthesis = payload["synthesis"]
    odds_provider = payload["odds_provider"]
    bot_fallback = payload["bot_fallback"]
    _cli.console.print(
        f"agent executor={agent['executor']} "
        f"langgraph={'yes' if agent['langgraph_available'] else 'no'}"
    )
    _cli.console.print(
        f"synthesis enabled={'yes' if synthesis['enabled'] else 'no'} "
        f"configured={'yes' if synthesis['configured'] else 'no'} "
        f"model={synthesis['model']}"
    )
    _cli.console.print(
        f"odds provider={odds_provider['name']} "
        f"configured={'yes' if odds_provider['configured'] else 'no'} "
        f"health-metrics={'yes' if odds_provider['health_metrics_available'] else 'no'}"
    )
    _cli.console.print(
        f"bot fallback enabled={'yes' if bot_fallback['enabled'] else 'no'} "
        f"configured={'yes' if bot_fallback['configured'] else 'no'} "
        f"model={bot_fallback['model']}"
    )


@_cli.app.command("match-brief")
def match_brief(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    query: str = _cli.typer.Option(..., "--query"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    workflow, session = _cli.build_agent_workflow()
    try:
        with _cli.traced_operation(
            settings,
            operation_name="cli.operator.match_brief",
            user_id=settings.default_user_id,
            tags=["operator", "brief", "match"],
            metadata={"fixture_id": fixture_id, "query": query, "format": format},
        ):
            result = workflow.run(fixture_id=fixture_id, query=query)
    finally:
        if session is not None:
            session.close()

    payload = _cli.build_match_brief_payload(result)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        if result.status == "failed":
            raise _cli.typer.Exit(code=2)
        return

    if result.status == "failed":
        _cli.console.print(payload["error"])
        raise _cli.typer.Exit(code=2)

    analysis = result.analysis
    if analysis is None:
        _cli.console.print("Match brief could not be generated.")
        raise _cli.typer.Exit(code=2)

    _cli.console.print(f"Match Brief: {analysis.fixture.home_team} vs {analysis.fixture.away_team}")
    _cli.console.print(f"Fixture: {analysis.fixture.fixture_id}")
    _cli.console.print(f"Query: {result.query}")
    _cli.console.print(f"Verdict: {analysis.judgment.verdict}")
    _cli.console.print(f"Confidence: {analysis.judgment.confidence}")
    _cli.console.print(f"Conflict: {analysis.conflict_state}")
    _cli.console.print(f"Counterargument: {analysis.judgment.counterargument}")
    _cli._print_brief_list("Core reasons", analysis.judgment.core_reasons)
    _cli._print_brief_list("Snapshot context", analysis.evidence.snapshot_summary)
    _cli._print_brief_list("Tactical evidence", analysis.evidence.tactical_summary)
    _cli._print_brief_list(
        "Market evidence",
        [*analysis.evidence.odds_summary, *analysis.evidence.market_shape_summary],
    )
    _cli._print_brief_list("Caveats", analysis.evidence.caveats)
    if result.generated_synthesis:
        _cli.console.print("Generated synthesis:")
        _cli.console.print(result.generated_synthesis)
    _cli.console.print(f"Agent: {result.executor} | nodes={' -> '.join(result.nodes)}")


@_cli.app.command("agent-analyze-match")
def agent_analyze_match(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    query: str = _cli.typer.Option(..., "--query"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    workflow, session = _cli.build_agent_workflow()
    try:
        with _cli.traced_operation(
            settings,
            operation_name="cli.agent.analysis.match",
            user_id=settings.default_user_id,
            tags=["agent", "analysis", "match"],
            metadata={"fixture_id": fixture_id, "query": query, "format": format},
        ):
            result = workflow.run(fixture_id=fixture_id, query=query)
    finally:
        if session is not None:
            session.close()

    payload = _cli.asdict(result)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        if result.status == "failed":
            raise _cli.typer.Exit(code=2)
        return

    _cli.console.print(f"Agent status: {result.status}")
    _cli.console.print(f"Agent nodes: {' -> '.join(result.nodes)}")
    if result.analysis is not None:
        _cli.console.print(f"Judgment: {result.analysis.judgment.verdict}")
        _cli.console.print(f"Confidence: {result.analysis.judgment.confidence}")
    if result.generated_synthesis:
        _cli.console.print("Generated synthesis:")
        _cli.console.print(result.generated_synthesis)
    if result.error:
        _cli.console.print(result.error)
        raise _cli.typer.Exit(code=2)


@_cli.app.command("bot-dry-run")
def bot_dry_run(
    message: str = _cli.typer.Option(..., "--message"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    workflow, session = _cli.build_agent_workflow()
    try:
        adapter = _cli.BotAdapter(
            workflow=workflow,
            payload_builder=_cli.build_match_brief_payload,
            fallback_provider=_cli.build_bot_fallback_provider(settings),
            # M2 cutover: v1 Poisson daily advisor (jczq_daily) retired — no
            # jczq_workflow wired; BotAdapter degrades `/jczq` gracefully.
            renjiu_workflow=_cli.ZucaiRenjiuBotWorkflow(
                service=_cli.build_zucai_renjiu_daily_service(),
                dry_run=True,
                value_bridge_factory=_cli._build_zucai_value_bridge_for_daily,
            ),
        )
        response = adapter.handle_message(message)
    finally:
        if session is not None:
            session.close()

    if format == "json":
        _cli.typer.echo(
            _cli.json.dumps(_cli.asdict(response), indent=2, sort_keys=True, default=str)
        )
        if response.status == "failed":
            raise _cli.typer.Exit(code=2)
        return

    _cli.console.print(response.text)
    if response.status == "failed":
        raise _cli.typer.Exit(code=2)
