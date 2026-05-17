"""Client-facing CLI commands.

Command functions live here and register on the shared
``nutmeg.interfaces.cli.app`` via ``@_cli.app.command()``. Every CLI-package
global (factories, helpers, options, re-exported imports) is reached through
``_cli`` so behaviour — including test monkeypatches on the ``cli`` package —
is identical to the pre-split single-module layout.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli


@_cli.app.command("client-status")
def client_status(
    user_id: str | None = _cli.typer.Option(None, "--user-id"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_client_service()
    try:
        payload = service.status(user_id=user_id)
    finally:
        if session is not None:
            session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"client status user={payload['user_id']} "
        f"health={payload['health']['health']} "
        f"plan={payload['entitlements']['plan']}"
    )


@_cli.app.command("client-feed")
def client_feed(
    league: str = _cli.typer.Option("epl", "--league"),
    days: int = _cli.typer.Option(3, "--days"),
    limit: int = _cli.typer.Option(5, "--limit"),
    user_id: str | None = _cli.typer.Option(None, "--user-id"),
    demo: bool = _cli.typer.Option(False, "--demo"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_client_service()
    try:
        payload = service.daily_feed(
            user_id=user_id,
            league=league,
            days=days,
            limit=limit,
            demo=demo,
        )
    finally:
        if session is not None:
            session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(
        f"Client feed: league={payload['league']} opportunities={len(payload['opportunities'])}"
    )
    for item in payload["opportunities"]:
        _cli.console.print(
            " | ".join(
                [
                    f"#{item['rank']}",
                    str(item["fixture_id"]),
                    f"{item['home_team']} vs {item['away_team']}",
                    f"actionability={item['actionability']}",
                    f"freshness={item['freshness']['health']}",
                    f"next={item['suggested_action']}",
                ]
            )
        )


@_cli.app.command("client-match")
def client_match(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    user_id: str | None = _cli.typer.Option(None, "--user-id"),
    information_sources_config: _cli.Path | None = _cli.CLIENT_INFORMATION_SOURCES_CONFIG_OPTION,
    information_cache_dir: _cli.Path | None = _cli.CLIENT_INFORMATION_CACHE_DIR_OPTION,
    live_information_fetch: bool = _cli.CLIENT_INFORMATION_LIVE_FETCH_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_client_service()
    if information_sources_config is not None:
        service.set_information_provider(
            _cli.build_live_fixture_information_service(
                manifest_path=information_sources_config,
                cache_dir=information_cache_dir,
                live_fetch=live_information_fetch,
            )
        )
    try:
        payload = service.match_workspace(user_id=user_id, fixture_id=fixture_id)
    finally:
        if session is not None:
            session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    judgment = payload.get("judgment") or {}
    _cli.console.print(
        f"Client match: {payload['fixture_id']} "
        f"actionability={payload['actionability']} "
        f"confidence={judgment.get('confidence')}"
    )
    _cli.console.print(str(judgment.get("verdict") or "No verdict"))


@_cli.app.command("client-question")
def client_question(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    question: str = _cli.typer.Option(..., "--question"),
    user_id: str | None = _cli.typer.Option(None, "--user-id"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_client_service()
    try:
        payload = service.answer_question(
            user_id=user_id,
            fixture_id=fixture_id,
            question=question,
        )
    finally:
        if session is not None:
            session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(payload["answer"])


@_cli.app.command("client-watchlist")
def client_watchlist(
    target_type: str = _cli.typer.Option("fixture", "--target-type"),
    target_id: str = _cli.typer.Option(..., "--target-id"),
    alert_preference: list[str] | None = _cli.ALERT_PREFERENCE_OPTION,
    user_id: str | None = _cli.typer.Option(None, "--user-id"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_client_service()
    resolved_user_id = user_id or getattr(service, "default_user_id", "owner")
    try:
        payload = service.save_watchlist_item(
            user_id=resolved_user_id,
            target_type=target_type,
            target_id=target_id,
            alert_preferences=alert_preference or [],
        )
    finally:
        if session is not None:
            session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(
        f"Watchlist saved: {payload['target_type']}={payload['target_id']} "
        f"alerts={','.join(payload['alert_preferences']) or '-'}"
    )


@_cli.app.command("client-alerts")
def client_alerts(
    user_id: str | None = _cli.typer.Option(None, "--user-id"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_client_service()
    resolved_user_id = user_id or getattr(service, "default_user_id", "owner")
    try:
        payload = service.alerts(user_id=resolved_user_id)
    finally:
        if session is not None:
            session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(f"Client alerts: {len(payload['alerts'])}")
    for alert in payload["alerts"]:
        _cli.console.print(
            " | ".join(
                [
                    str(alert.get("alert_id")),
                    str(alert.get("fixture_id")),
                    str(alert.get("change_type")),
                    str(alert.get("severity")),
                    str(alert.get("after_summary")),
                ]
            )
        )


@_cli.app.command("client-prediction-record")
def client_prediction_record(
    fixture_id: str = _cli.typer.Option(..., "--fixture-id"),
    pick: str = _cli.typer.Option(..., "--pick"),
    source_audit_id: str | None = _cli.typer.Option(None, "--source-audit-id"),
    client_notes: str | None = _cli.typer.Option(None, "--client-notes"),
    user_id: str | None = _cli.typer.Option(None, "--user-id"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service, session = _cli.build_client_service()
    resolved_user_id = user_id or getattr(service, "default_user_id", "owner")
    try:
        payload = service.record_prediction(
            user_id=resolved_user_id,
            fixture_id=fixture_id,
            pick=pick,
            source_audit_id=source_audit_id,
            client_notes=client_notes,
        )
    finally:
        if session is not None:
            session.close()

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(
        f"Client prediction recorded: id={payload['prediction_id']} "
        f"fixture={payload['fixture_id']} pick={payload['pick']}"
    )


@_cli.app.command("client-web")
def client_web(
    host: str = _cli.typer.Option("127.0.0.1", "--host"),
    port: int = _cli.typer.Option(8765, "--port"),
) -> None:
    import uvicorn

    service, _session = _cli.build_client_service()
    uvicorn.run(_cli.create_client_app(service=service), host=host, port=port)
