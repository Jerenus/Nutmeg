import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings, clear_settings_cache
from nutmeg.interfaces import cli as cli_module
from nutmeg.interfaces.cli import app
from nutmeg.ontology.repository.migrations import MIGRATIONS
from nutmeg.ontology.wiring import build_ontology_kernel
from tests.ontology.test_protected_ticket_actions import AT
from tests.ontology.test_ticket_confirmation import _approved


def _configure(monkeypatch, owners="111") -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", owners)
    clear_settings_cache()


def test_ticket_confirmation_help_exposes_protected_request_options() -> None:
    result = CliRunner().invoke(app, ["ticket-confirmation", "request", "--help"])

    assert result.exit_code == 0
    assert "--data-dir" in result.stdout
    assert "--ticket-artifact-id" in result.stdout
    assert "--chat-id" in result.stdout
    assert "--dry-run" in result.stdout


def test_ticket_confirmation_request_defaults_to_redacted_dry_run(
    tmp_path: Path, monkeypatch
) -> None:
    kernel, _forecast_id, artifact = _approved(tmp_path)
    _configure(monkeypatch)

    result = CliRunner().invoke(app, [
        "ticket-confirmation",
        "request",
        "--data-dir", str(tmp_path / "data"),
        "--ticket-artifact-id", artifact.ticket_artifact_id,
        "--requested-at", AT.isoformat(),
    ])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["dispatch_state"] == "dry_run"
    assert payload["ticket_artifact_id"] == artifact.ticket_artifact_id
    assert payload["callback_bytes"] <= 64
    assert "nonce" not in result.stdout.lower()
    assert "callback_data" not in result.stdout
    assert "telegram-secret" not in result.stdout
    assert kernel.status().schema_version == MIGRATIONS[-1].version


def test_ticket_confirmation_request_rejects_non_owner_before_live_send(
    tmp_path: Path, monkeypatch
) -> None:
    _kernel, _forecast_id, artifact = _approved(tmp_path)
    _configure(monkeypatch)

    result = CliRunner().invoke(app, [
        "ticket-confirmation",
        "request",
        "--data-dir", str(tmp_path / "data"),
        "--ticket-artifact-id", artifact.ticket_artifact_id,
        "--chat-id", "999",
        "--requested-at", AT.isoformat(),
        "--no-dry-run",
    ])

    assert result.exit_code == 1
    assert "not allowlisted" in result.stdout


def test_ticket_confirmation_request_requires_chat_when_multiple_owners(
    tmp_path: Path, monkeypatch
) -> None:
    _kernel, _forecast_id, artifact = _approved(tmp_path)
    _configure(monkeypatch, owners="111,222")

    result = CliRunner().invoke(app, [
        "ticket-confirmation",
        "request",
        "--data-dir", str(tmp_path / "data"),
        "--ticket-artifact-id", artifact.ticket_artifact_id,
        "--requested-at", AT.isoformat(),
    ])

    assert result.exit_code == 1
    assert "--chat-id" in result.stdout


def test_ticket_confirmation_request_rejects_uninitialized_data_root(
    tmp_path: Path, monkeypatch
) -> None:
    _configure(monkeypatch)

    result = CliRunner().invoke(app, [
        "ticket-confirmation",
        "request",
        "--data-dir", str(tmp_path / "missing"),
        "--ticket-artifact-id", "tat-missing",
        "--requested-at", AT.isoformat(),
    ])

    assert result.exit_code == 1
    assert "initialized, healthy, and current" in result.stdout


def test_bot_runner_installs_handler_only_for_current_kernel(
    tmp_path: Path, monkeypatch
) -> None:
    healthy_settings = AppSettings(
        data_dir=tmp_path / "healthy",
        telegram_bot_token="telegram-secret",
        telegram_allowed_chat_ids="111",
    )
    build_ontology_kernel(healthy_settings).initialize()
    unhealthy_settings = AppSettings(
        data_dir=tmp_path / "missing",
        telegram_bot_token="telegram-secret",
        telegram_allowed_chat_ids="111",
    )
    monkeypatch.setattr(cli_module, "build_agent_workflow", lambda: (None, None))

    healthy = cli_module.build_telegram_bot_runner(healthy_settings)
    unhealthy = cli_module.build_telegram_bot_runner(unhealthy_settings)

    assert healthy._confirmation_handler is not None
    assert unhealthy._confirmation_handler is None
