#!/usr/bin/env python3
"""Strict local boundary for OpenClaw-owned Telegram confirmation callbacks."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, Callable, Literal, Mapping, TextIO

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
)

CONTRACT_VERSION = "openclaw-telegram-interactive-v1"
PLUGIN_ID = "nutmeg-ticket-confirmation"
MAX_STDIN_BYTES = 8_192
MAX_PAST_SKEW = timedelta(seconds=10)
MAX_FUTURE_SKEW = timedelta(seconds=2)


class BridgeInputError(ValueError):
    """A safe validation failure at the local OpenClaw bridge boundary."""


class OpenClawTelegramInteractiveV1(BaseModel):
    """Closed callback shape serialized by the trusted OpenClaw plugin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["openclaw-telegram-interactive-v1"]
    plugin_id: Literal["nutmeg-ticket-confirmation"]
    account_id: StrictStr
    owner_instance_id: StrictStr
    callback_query_id: StrictStr
    sender_id: StrictStr
    chat_id: StrictStr
    message_id: StrictStr
    authorized: StrictBool
    namespace: Literal["ntc"]
    callback_data: StrictStr
    server_ingress_at: datetime

    @field_validator(
        "account_id",
        "owner_instance_id",
        "callback_query_id",
        "sender_id",
        "chat_id",
        "message_id",
    )
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("identity fields must be nonblank canonical strings")
        return value

    @field_validator("callback_data")
    @classmethod
    def _callback_namespace(cls, value: str) -> str:
        if not value.startswith("ntc:") or not value.removeprefix("ntc:"):
            raise ValueError("callback_data must contain an opaque ntc payload")
        try:
            size = len(value.encode("ascii"))
        except UnicodeEncodeError as error:
            raise ValueError("callback_data must be ASCII") from error
        if size > 64:
            raise ValueError("callback_data exceeds Telegram's 64-byte limit")
        return value

    @field_validator("server_ingress_at")
    @classmethod
    def _aware_ingress(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("server_ingress_at must be timezone-aware")
        return value


class OpenClawTelegramHeartbeatV1(BaseModel):
    """Closed lease-pulse shape serialized by the trusted OpenClaw plugin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["openclaw-telegram-interactive-v1"]
    plugin_id: Literal["nutmeg-ticket-confirmation"]
    account_id: Literal["nutmeg"]
    owner_instance_id: StrictStr
    transport_label: Literal["openclaw-telegram"]
    router_version: StrictStr
    lease_seconds: StrictInt = Field(ge=30, le=300)

    @field_validator("owner_instance_id", "router_version")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("heartbeat identity fields must be canonical strings")
        return value

def read_single_json_document(
    stream: BinaryIO | TextIO,
    *,
    max_bytes: int = MAX_STDIN_BYTES,
) -> dict[str, object]:
    """Read exactly one bounded JSON object without accepting trailing documents."""
    raw = stream.read(max_bytes + 1)
    byte_count = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    if byte_count > max_bytes:
        raise BridgeInputError("stdin document is too large")
    if isinstance(raw, str):
        text = raw
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise BridgeInputError("stdin must be UTF-8 JSON") from error
    decoder = json.JSONDecoder()
    stripped = text.lstrip()
    try:
        document, end = decoder.raw_decode(stripped)
    except json.JSONDecodeError as error:
        raise BridgeInputError("stdin must contain a single JSON object") from error
    if stripped[end:].strip():
        raise BridgeInputError("stdin must contain a single JSON object")
    if not isinstance(document, dict):
        raise BridgeInputError("stdin JSON document must be an object")
    return document


def require_environment_authority(
    update: OpenClawTelegramInteractiveV1,
    environment: Mapping[str, str],
) -> tuple[str, str]:
    """Resolve process authority separately from the untrusted stdin claims."""
    account_id = environment.get("NUTMEG_TELEGRAM_ACCOUNT_ID", "")
    owner_instance_id = environment.get(
        "NUTMEG_TELEGRAM_OWNER_INSTANCE_ID",
        "",
    )
    require_trusted_owner(
        update,
        trusted_account_id=account_id or None,
        owner_instance_id=owner_instance_id or None,
        bridge_received_at=update.server_ingress_at,
    )
    return account_id, owner_instance_id


def require_trusted_owner(
    update: OpenClawTelegramInteractiveV1,
    *,
    trusted_account_id: str | None,
    owner_instance_id: str | None,
    bridge_received_at: datetime,
) -> None:
    """Validate owner claims and the plugin-captured ingress timestamp."""
    if bridge_received_at.tzinfo is None or bridge_received_at.utcoffset() is None:
        raise BridgeInputError("bridge_received_at must be timezone-aware")
    if trusted_account_id != "nutmeg" or update.account_id != trusted_account_id:
        raise BridgeInputError("Telegram account authority mismatch")
    if not owner_instance_id or update.owner_instance_id != owner_instance_id:
        raise BridgeInputError("Telegram owner authority mismatch")
    if update.plugin_id != PLUGIN_ID:
        raise BridgeInputError("Telegram plugin authority mismatch")
    age = bridge_received_at - update.server_ingress_at
    if age > MAX_PAST_SKEW or age < -MAX_FUTURE_SKEW:
        raise BridgeInputError("Telegram callback timestamp skew is outside allowed window")


def require_ntc_callback(
    update: OpenClawTelegramInteractiveV1,
) -> OpenClawTelegramInteractiveV1:
    """Reject any callback that cannot enter the protected ntc route."""
    if (
        not update.authorized
        or update.namespace != "ntc"
        or not update.callback_data.startswith("ntc:")
        or not update.callback_data.removeprefix("ntc:")
    ):
        raise BridgeInputError("callback is not an authorized ntc confirmation")
    return update


def _parse_cli_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("subcommand", choices=("callback", "heartbeat"))
    parser.add_argument("--contract-version", required=True)
    try:
        options, unknown = parser.parse_known_args(argv)
    except (argparse.ArgumentError, SystemExit) as error:
        raise BridgeInputError("invalid bridge command") from error
    if unknown or options.contract_version != CONTRACT_VERSION:
        raise BridgeInputError("invalid bridge command")
    return options


def _result_message(result: object, fallback: str) -> str:
    if isinstance(result, Mapping):
        value = result.get("message")
    else:
        value = getattr(result, "message", None)
    if not isinstance(value, str) or not value.strip():
        return fallback
    return value.strip()[:160]


def run_cli(
    argv: list[str],
    *,
    stdin: BinaryIO | TextIO,
    stdout: TextIO,
    stderr: TextIO,
    environment: Mapping[str, str],
    received_at: datetime,
    ingest_callback: Callable[..., object] | None = None,
    pulse_heartbeat: Callable[..., object] | None = None,
) -> int:
    """Execute one closed bridge request without reflecting untrusted input."""
    try:
        options = _parse_cli_args(argv)
        document = read_single_json_document(stdin)
        if options.subcommand == "callback":
            update = OpenClawTelegramInteractiveV1.model_validate(document)
            account_id, owner_instance_id = require_environment_authority(
                update,
                environment,
            )
            require_trusted_owner(
                update,
                trusted_account_id=account_id,
                owner_instance_id=owner_instance_id,
                bridge_received_at=received_at,
            )
            require_ntc_callback(update)
            handler = ingest_callback or _default_ingest_callback
            result = handler(
                update,
                trusted_account_id=account_id,
                owner_instance_id=owner_instance_id,
                bridge_received_at=received_at,
            )
            message = _result_message(result, "Placement recorded.")
        else:
            heartbeat = OpenClawTelegramHeartbeatV1.model_validate(document)
            account_id = environment.get("NUTMEG_TELEGRAM_ACCOUNT_ID", "")
            owner_instance_id = environment.get(
                "NUTMEG_TELEGRAM_OWNER_INSTANCE_ID",
                "",
            )
            if (
                account_id != "nutmeg"
                or heartbeat.account_id != account_id
                or not owner_instance_id
                or heartbeat.owner_instance_id != owner_instance_id
            ):
                raise BridgeInputError("Telegram owner authority mismatch")
            handler = pulse_heartbeat or _default_pulse_heartbeat
            result = handler(
                heartbeat,
                trusted_account_id=account_id,
                owner_instance_id=owner_instance_id,
                observed_at=received_at,
            )
            message = _result_message(result, "Owner heartbeat recorded.")
        stdout.write(json.dumps({"ok": True, "message": message}) + "\n")
        return 0
    except Exception:
        stderr.write("Nutmeg confirmation bridge rejected the request.\n")
        return 2


def _default_pulse_heartbeat(
    heartbeat: OpenClawTelegramHeartbeatV1,
    *,
    trusted_account_id: str,
    owner_instance_id: str,
    observed_at: datetime,
) -> dict[str, str]:
    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from nutmeg.ontology.wiring import build_ontology_kernel
    from nutmeg.services.telegram_ticket_confirmation import (
        TelegramOwnerHeartbeatService,
    )

    settings = AppSettings(_env_file=None)
    kernel = build_ontology_kernel(settings)
    if not kernel.status().initialized:
        raise BridgeInputError("ontology is not initialized")
    action_service = ActionService(lambda: OntologyUnitOfWork(kernel.engine))
    service = TelegramOwnerHeartbeatService(
        action_service=action_service,
        account_id=trusted_account_id,
        owner_instance_id=owner_instance_id,
        transport_label=heartbeat.transport_label,
        owner_mode="openclaw",
        router_version=heartbeat.router_version,
        lease_duration=timedelta(seconds=heartbeat.lease_seconds),
    )
    service.pulse(observed_at=observed_at)
    return {"message": "Owner heartbeat recorded."}


def _default_ingest_callback(
    update: OpenClawTelegramInteractiveV1,
    *,
    trusted_account_id: str,
    owner_instance_id: str,
    bridge_received_at: datetime,
) -> object:
    from nutmeg.services.telegram_ticket_confirmation import (
        ingest_openclaw_telegram_update,
    )

    return ingest_openclaw_telegram_update(
        update,
        trusted_account_id=trusted_account_id,
        owner_instance_id=owner_instance_id,
        bridge_received_at=bridge_received_at,
    )


def main() -> int:
    received_at = datetime.now(UTC)
    return run_cli(
        sys.argv[1:],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        environment=os.environ,
        received_at=received_at,
    )


__all__ = [
    "BridgeInputError",
    "CONTRACT_VERSION",
    "OpenClawTelegramHeartbeatV1",
    "OpenClawTelegramInteractiveV1",
    "read_single_json_document",
    "require_environment_authority",
    "require_ntc_callback",
    "require_trusted_owner",
    "run_cli",
]


if __name__ == "__main__":
    raise SystemExit(main())
