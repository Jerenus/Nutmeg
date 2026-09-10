from __future__ import annotations

import importlib.util
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "scripts" / "openclaw" / "nutmeg_ticket_confirmation_bridge.py"
RECEIVED_AT = datetime(2026, 9, 5, 1, 2, 10, tzinfo=UTC)


def _load_bridge():
    spec = importlib.util.spec_from_file_location(
        "nutmeg_ticket_confirmation_bridge",
        BRIDGE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _callback(**updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "contract_version": "openclaw-telegram-interactive-v1",
        "plugin_id": "nutmeg-ticket-confirmation",
        "account_id": "nutmeg",
        "owner_instance_id": "openclaw-primary",
        "callback_query_id": "callback-1",
        "sender_id": "222",
        "chat_id": "111",
        "message_id": "7",
        "authorized": True,
        "namespace": "ntc",
        "callback_data": "ntc:opaque-value",
        "server_ingress_at": "2026-09-05T01:02:03.456Z",
    }
    document.update(updates)
    return document


def test_callback_contract_is_strict_and_keeps_nonce_opaque() -> None:
    bridge = _load_bridge()

    parsed = bridge.OpenClawTelegramInteractiveV1.model_validate(_callback())

    assert parsed.callback_data == "ntc:opaque-value"
    assert parsed.server_ingress_at == datetime(
        2026,
        9,
        5,
        1,
        2,
        3,
        456000,
        tzinfo=UTC,
    )
    assert not hasattr(parsed, "ticket_artifact_id")
    assert not hasattr(parsed, "client_timestamp")


@pytest.mark.parametrize(
    "extra",
    (
        {"ticket_artifact_id": "artifact-injection"},
        {"nonce": "plaintext-nonce"},
        {"client_timestamp": "2026-09-05T01:02:03Z"},
        {"payload": {"arbitrary": True}},
    ),
)
def test_callback_contract_rejects_unknown_or_privileged_fields(
    extra: dict[str, object],
) -> None:
    bridge = _load_bridge()

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        bridge.OpenClawTelegramInteractiveV1.model_validate(_callback(**extra))


def test_stdin_reader_accepts_exactly_one_bounded_json_object() -> None:
    bridge = _load_bridge()
    payload = '{"contract_version":"openclaw-telegram-interactive-v1"}'

    assert bridge.read_single_json_document(io.StringIO(payload)) == {
        "contract_version": "openclaw-telegram-interactive-v1"
    }
    for invalid in (
        payload + "\n{}",
        "[]",
        "not-json",
        '{"x":"' + ("a" * 20_000) + '"}',
    ):
        with pytest.raises(ValueError):
            bridge.read_single_json_document(io.StringIO(invalid))


@pytest.mark.parametrize(
    ("trusted_account", "trusted_owner", "message"),
    (
        (None, "openclaw-primary", "account authority"),
        ("other", "openclaw-primary", "account authority"),
        ("nutmeg", None, "owner authority"),
        ("nutmeg", "other-owner", "owner authority"),
    ),
)
def test_environment_authority_must_match_the_envelope_before_ingest(
    trusted_account: str | None,
    trusted_owner: str | None,
    message: str,
) -> None:
    bridge = _load_bridge()
    update = bridge.OpenClawTelegramInteractiveV1.model_validate(_callback())

    with pytest.raises(ValueError, match=message):
        bridge.require_trusted_owner(
            update,
            trusted_account_id=trusted_account,
            owner_instance_id=trusted_owner,
            bridge_received_at=RECEIVED_AT,
        )


@pytest.mark.parametrize(
    "ingress_at",
    (
        RECEIVED_AT - timedelta(seconds=10, microseconds=1),
        RECEIVED_AT + timedelta(seconds=2, microseconds=1),
    ),
)
def test_bridge_rejects_callback_ingress_outside_the_process_clock_window(
    ingress_at: datetime,
) -> None:
    bridge = _load_bridge()
    update = bridge.OpenClawTelegramInteractiveV1.model_validate(
        _callback(server_ingress_at=ingress_at.isoformat())
    )

    with pytest.raises(ValueError, match="timestamp skew"):
        bridge.require_trusted_owner(
            update,
            trusted_account_id="nutmeg",
            owner_instance_id="openclaw-primary",
            bridge_received_at=RECEIVED_AT,
        )


@pytest.mark.parametrize(
    "ingress_at",
    (RECEIVED_AT - timedelta(seconds=10), RECEIVED_AT + timedelta(seconds=2)),
)
def test_bridge_accepts_both_timestamp_skew_boundaries(ingress_at: datetime) -> None:
    bridge = _load_bridge()
    update = bridge.OpenClawTelegramInteractiveV1.model_validate(
        _callback(server_ingress_at=ingress_at.isoformat())
    )

    bridge.require_trusted_owner(
        update,
        trusted_account_id="nutmeg",
        owner_instance_id="openclaw-primary",
        bridge_received_at=RECEIVED_AT,
    )


def test_callback_requires_authorized_ntc_namespace_and_opaque_value() -> None:
    bridge = _load_bridge()

    for update in (
        _callback(authorized=False),
        _callback(namespace="other"),
        _callback(callback_data="other:value"),
        _callback(callback_data="ntc:"),
    ):
        with pytest.raises((ValidationError, ValueError)):
            parsed = bridge.OpenClawTelegramInteractiveV1.model_validate(update)
            bridge.require_ntc_callback(parsed)


def test_callback_cli_uses_trusted_ingress_and_delegates_one_attested_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _load_bridge()
    calls = []

    def ingest(update, **kwargs):
        calls.append((update, kwargs))
        return {"message": "Placement recorded."}

    stdout = io.StringIO()
    exit_code = bridge.run_cli(
        ["callback", "--contract-version", bridge.CONTRACT_VERSION],
        stdin=io.StringIO(json.dumps(_callback())),
        stdout=stdout,
        stderr=io.StringIO(),
        environment={
            "NUTMEG_TELEGRAM_ACCOUNT_ID": "nutmeg",
            "NUTMEG_TELEGRAM_OWNER_INSTANCE_ID": "openclaw-primary",
        },
        received_at=RECEIVED_AT,
        ingest_callback=ingest,
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == {
        "ok": True,
        "message": "Placement recorded.",
    }
    assert len(calls) == 1
    update, kwargs = calls[0]
    assert update.callback_data == "ntc:opaque-value"
    assert kwargs == {
        "trusted_account_id": "nutmeg",
        "owner_instance_id": "openclaw-primary",
        "bridge_received_at": RECEIVED_AT,
    }


def test_heartbeat_cli_delegates_closed_registration_without_business_payload() -> None:
    bridge = _load_bridge()
    calls = []
    heartbeat = {
        "contract_version": bridge.CONTRACT_VERSION,
        "plugin_id": bridge.PLUGIN_ID,
        "account_id": "nutmeg",
        "owner_instance_id": "openclaw-primary",
        "transport_label": "openclaw-telegram",
        "router_version": "ntc-v1",
        "lease_seconds": 90,
    }

    def pulse(document, **kwargs):
        calls.append((document, kwargs))
        return {"message": "Owner heartbeat recorded."}

    stdout = io.StringIO()
    exit_code = bridge.run_cli(
        ["heartbeat", "--contract-version", bridge.CONTRACT_VERSION],
        stdin=io.StringIO(json.dumps(heartbeat)),
        stdout=stdout,
        stderr=io.StringIO(),
        environment={
            "NUTMEG_TELEGRAM_ACCOUNT_ID": "nutmeg",
            "NUTMEG_TELEGRAM_OWNER_INSTANCE_ID": "openclaw-primary",
        },
        received_at=RECEIVED_AT,
        pulse_heartbeat=pulse,
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0][0].lease_seconds == 90
    assert calls[0][1]["observed_at"] == RECEIVED_AT
    assert json.loads(stdout.getvalue())["ok"] is True


def test_cli_rejects_unknown_args_without_echoing_callback_data() -> None:
    bridge = _load_bridge()
    secret = "ntc:opaque-secret-value"
    stderr = io.StringIO()

    exit_code = bridge.run_cli(
        ["callback", "--contract-version", bridge.CONTRACT_VERSION, "--payload", secret],
        stdin=io.StringIO("{}"),
        stdout=io.StringIO(),
        stderr=stderr,
        environment={},
        received_at=RECEIVED_AT,
    )

    assert exit_code != 0
    assert secret not in stderr.getvalue()
