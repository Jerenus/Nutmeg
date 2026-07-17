from typer.testing import CliRunner

import nutmeg.interfaces.cli.notifications as notification_cli
from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_notification_status_json_redacts_destinations(monkeypatch) -> None:
    monkeypatch.setattr(
        notification_cli,
        "_status_payload",
        lambda since: {
            "since": since,
            "counts": {"sent": 1},
            "notifications": [
                {"notification_id": "N-1", "destination": "***8415"}
            ],
        },
    )

    result = runner.invoke(
        app, ["notification-status", "--since", "7d", "--format", "json"]
    )

    assert result.exit_code == 0
    assert "***8415" in result.output
    assert "7627818415" not in result.output


def test_notification_status_rejects_invalid_since() -> None:
    result = runner.invoke(app, ["notification-status", "--since", "zero"])

    assert result.exit_code == 2
    assert "since must" in result.output


def test_notification_retry_requires_exactly_one_selector() -> None:
    result = runner.invoke(app, ["notification-retry"])

    assert result.exit_code == 2
    assert "exactly one" in result.output
