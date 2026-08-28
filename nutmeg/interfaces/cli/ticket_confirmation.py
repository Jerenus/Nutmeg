"""CLI for owner-only protected Telegram ticket confirmation."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.ontology.actions.models import canonical_json

ticket_confirmation_app = _cli.typer.Typer(
    help="Protected owner ticket confirmation"
)
_cli.app.add_typer(ticket_confirmation_app, name="ticket-confirmation")

_DATA_DIR_OPTION = _cli.typer.Option(..., "--data-dir")
_TICKET_ARTIFACT_OPTION = _cli.typer.Option(..., "--ticket-artifact-id")


def _at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("requested-at must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("requested-at must be timezone-aware")
    return parsed.astimezone(UTC)


def _owner(chat_id: int | None, allowed: set[int]) -> int:
    if chat_id is not None:
        if chat_id not in allowed:
            raise ValueError(f"chat id {chat_id} is not allowlisted")
        return chat_id
    if len(allowed) != 1:
        raise ValueError("--chat-id is required unless exactly one owner is configured")
    return next(iter(allowed))


@ticket_confirmation_app.command("request")
def request_ticket_confirmation(
    data_dir: Path = _DATA_DIR_OPTION,
    ticket_artifact_id: str = _TICKET_ARTIFACT_OPTION,
    chat_id: int | None = _cli.typer.Option(None, "--chat-id"),
    requested_at: str | None = _cli.typer.Option(None, "--requested-at"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Issue a five-minute challenge and optionally send its owner-only button."""
    try:
        settings = _cli.get_settings()
        service, allowed = _cli.build_telegram_ticket_confirmation_service(
            settings, data_dir
        )
        owner = _owner(chat_id, allowed)
        prepared = service.request_confirmation(
            ticket_artifact_id=ticket_artifact_id,
            chat_id=owner,
            dry_run=dry_run,
            requested_at=_at(requested_at),
        )
        payload = prepared.to_public_dict()
        payload["dispatch_state"] = "dry_run" if dry_run else "sent"
        _cli.typer.echo(canonical_json(payload))
    except (OSError, RuntimeError, ValueError) as error:
        _cli.typer.echo(canonical_json({
            "code": "ticket_confirmation_blocked",
            "message": str(error),
        }))
        raise _cli.typer.Exit(code=1) from error
