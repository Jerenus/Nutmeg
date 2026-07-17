"""Outbound notification audit and retry commands."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta

import nutmeg.interfaces.cli as _cli
from nutmeg.notifications.models import redact_destination
from nutmeg.notifications.wiring import build_notification_service


@_cli.app.command("notification-status")
def notification_status(
    since: str = _cli.typer.Option("7d", "--since"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        payload = _status_payload(since)
    except ValueError as exc:
        raise _cli.typer.BadParameter(str(exc), param_hint="--since") from exc
    _print_payload(payload, format=format)


@_cli.app.command("notification-show")
def notification_show(
    notification_id: str = _cli.typer.Option(..., "--notification-id"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = build_notification_service()
    try:
        bundle = service.repository.get_bundle(notification_id)
    except KeyError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    _print_payload(_bundle_payload(bundle), format=format)


@_cli.app.command("notification-retry")
def notification_retry(
    notification_id: str | None = _cli.typer.Option(None, "--notification-id"),
    failed_required: bool = _cli.typer.Option(False, "--failed-required"),
    include_permanent: bool = _cli.typer.Option(False, "--include-permanent"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    if (notification_id is None) == (not failed_required):
        raise _cli.typer.BadParameter(
            "exactly one of --notification-id or --failed-required is required"
        )
    service = build_notification_service()
    try:
        outcomes = (
            (service.retry(notification_id, include_permanent=include_permanent),)
            if notification_id is not None
            else service.retry_failed_required()
        )
    except KeyError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc
    payload = {"outcomes": [outcome.to_dict() for outcome in outcomes]}
    _print_payload(payload, format=format)
    if any(not outcome.is_success for outcome in outcomes):
        raise _cli.typer.Exit(code=1)


def _status_payload(since: str) -> dict:
    delta = _parse_since(since)
    threshold = datetime.now(UTC) - delta
    service = build_notification_service()
    notifications = service.repository.list_recent(threshold)
    counts = Counter(item.status.value for item in notifications)
    return {
        "since": since,
        "generated_at": datetime.now(UTC).isoformat(),
        "counts": dict(sorted(counts.items())),
        "notifications": [
            {
                "notification_id": item.notification_id,
                "kind": item.kind,
                "business_key": item.business_key,
                "stage": item.stage,
                "revision": item.revision,
                "status": item.status.value,
                "created_at": item.created_at.isoformat(),
            }
            for item in notifications
        ],
    }


def _bundle_payload(bundle) -> dict:
    notification = bundle.notification
    return {
        "notification": {
            "notification_id": notification.notification_id,
            "kind": notification.kind,
            "business_key": notification.business_key,
            "stage": notification.stage,
            "revision": notification.revision,
            "status": notification.status.value,
            "subject": notification.subject,
            "created_at": notification.created_at.isoformat(),
            "updated_at": notification.updated_at.isoformat(),
        },
        "artifacts": [
            {
                "path": str(item.path),
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "media_type": item.media_type,
            }
            for item in bundle.artifacts
        ],
        "deliveries": [
            {
                "delivery_id": item.delivery_id,
                "channel": item.channel,
                "recipient_key": item.recipient_key,
                "destination": redact_destination(item.destination),
                "required": item.required,
                "status": item.status.value,
                "attempt_count": item.attempt_count,
                "provider_message_id": item.provider_message_id,
                "last_error_code": item.last_error_code,
                "last_error_message": item.last_error_message,
            }
            for item in bundle.deliveries
        ],
        "attempts": [
            {
                "attempt_id": item.attempt_id,
                "delivery_id": item.delivery_id,
                "attempt_number": item.attempt_number,
                "outcome": item.outcome.value,
                "started_at": item.started_at.isoformat(),
                "completed_at": (
                    item.completed_at.isoformat() if item.completed_at is not None else None
                ),
                "error_code": item.error_code,
                "error_message": item.error_message,
                "retryable": item.retryable,
                "possible_duplicate": item.possible_duplicate,
            }
            for item in bundle.attempts
        ],
    }


def _parse_since(value: str) -> timedelta:
    if len(value) < 2 or value[-1] not in {"h", "d"}:
        raise ValueError("since must be a positive duration such as 12h or 7d")
    try:
        amount = int(value[:-1])
    except ValueError as exc:
        raise ValueError("since must be a positive duration such as 12h or 7d") from exc
    if amount <= 0:
        raise ValueError("since must be a positive duration such as 12h or 7d")
    return timedelta(hours=amount) if value[-1] == "h" else timedelta(days=amount)


def _print_payload(payload: dict, *, format: str) -> None:
    if format == "json":
        _cli.typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if format != "text":
        raise _cli.typer.BadParameter("format must be text or json", param_hint="--format")
    _cli.console.print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
