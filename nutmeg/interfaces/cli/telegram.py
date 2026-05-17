"""Telegram bot CLI commands.

Command functions live here and register on the shared
``nutmeg.interfaces.cli.app`` via ``@_cli.app.command()``. Every CLI-package
global (factories, helpers, options, re-exported imports) is reached through
``_cli`` so behaviour — including test monkeypatches on the ``cli`` package —
is identical to the pre-split single-module layout.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli


@_cli.app.command("telegram-bot-status")
def telegram_bot_status(
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    payload = _cli.build_telegram_status_payload(settings)
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(
        f"telegram configured={'yes' if payload['configured'] else 'no'} "
        f"allowlist={'yes' if payload['allowed_chat_ids_configured'] else 'no'} "
        f"allowed-chats={payload['allowed_chat_count']}"
    )


@_cli.app.command("telegram-bot-poll-once")
def telegram_bot_poll_once(
    offset: int | None = _cli.typer.Option(None, "--offset"),
    timeout: int = _cli.typer.Option(10, "--timeout"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    try:
        runner = _cli.build_telegram_bot_runner(settings)
        summary = runner.poll_once(offset=offset, timeout=timeout)
    except ValueError as exc:
        payload = {"status": "failed", "error": str(exc)}
        if format == "json":
            _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = {
        "updates_seen": summary.updates_seen,
        "messages_handled": summary.messages_handled,
        "messages_denied": summary.messages_denied,
        "messages_ignored": summary.messages_ignored,
        "next_offset": summary.next_offset,
    }
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(
        f"updates={summary.updates_seen} handled={summary.messages_handled} "
        f"denied={summary.messages_denied} ignored={summary.messages_ignored} "
        f"next_offset={summary.next_offset}"
    )


@_cli.app.command("telegram-bot-run")
def telegram_bot_run(
    offset: int | None = _cli.typer.Option(None, "--offset"),
    timeout: int = _cli.typer.Option(10, "--timeout"),
    poll_interval: float = _cli.typer.Option(2.0, "--poll-interval"),
    max_polls: int | None = _cli.typer.Option(None, "--max-polls"),
    offset_file: _cli.Path | None = _cli.TELEGRAM_OFFSET_FILE_OPTION,
    no_offset_file: bool = _cli.TELEGRAM_NO_OFFSET_FILE_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    settings = _cli.get_settings()
    offset_store = None
    resolved_offset_file = None
    offset_source = "explicit" if offset is not None else "none"
    if not no_offset_file:
        resolved_offset_file = offset_file or _cli.default_telegram_offset_path(settings)
        offset_store = _cli.TelegramOffsetStore(resolved_offset_file)
        if offset is None:
            stored_offset = offset_store.read()
            if stored_offset is not None:
                offset = stored_offset
                offset_source = "store"
            else:
                offset_source = "telegram"
    try:
        daemon = _cli.build_telegram_polling_daemon(
            settings,
            poll_interval_seconds=poll_interval,
            offset_store=offset_store,
        )
        summary = daemon.run(offset=offset, timeout=timeout, max_polls=max_polls)
    except ValueError as exc:
        payload = {"status": "failed", "error": str(exc)}
        if format == "json":
            _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = _cli.telegram_daemon_summary_payload(
        summary,
        offset_persistence_enabled=offset_store is not None,
        offset_source=offset_source,
        offset_file=resolved_offset_file,
    )
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(
        f"polls={summary.polls_run} updates={summary.updates_seen} "
        f"handled={summary.messages_handled} denied={summary.messages_denied} "
        f"ignored={summary.messages_ignored} next_offset={summary.next_offset} "
        f"stop={summary.stop_reason} offset_source={offset_source} "
        f"offset_file={resolved_offset_file}"
    )
