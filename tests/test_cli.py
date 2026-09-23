from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import clear_settings_cache
from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_telegram_bot_status_reports_configuration_without_token(monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111,222")
    clear_settings_cache()

    result = runner.invoke(app, ["telegram-bot-status", "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["configured"] is True
    assert payload["allowed_chat_count"] == 2
    assert payload["allowed_chat_ids_configured"] is True
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_poll_once_uses_runner_builder(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        updates_seen = 2
        messages_handled = 1
        messages_denied = 1
        messages_ignored = 0
        next_offset = 12

    class StubRunner:
        def poll_once(self, *, offset: int | None, timeout: int):
            assert offset == 10
            assert timeout == 1
            return StubSummary()

    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(cli_module, "build_telegram_bot_runner", lambda settings: StubRunner())

    result = runner.invoke(
        app,
        ["telegram-bot-poll-once", "--offset", "10", "--timeout", "1", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["updates_seen"] == 2
    assert payload["messages_handled"] == 1
    assert payload["messages_denied"] == 1
    assert payload["next_offset"] == 12
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_uses_daemon_builder(monkeypatch) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 2
        updates_seen = 3
        messages_handled = 2
        messages_denied = 1
        messages_ignored = 0
        next_offset = 13
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 10
            assert timeout == 1
            assert max_polls == 2
            return StubSummary()

    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--offset",
            "10",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "2",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["polls_run"] == 2
    assert payload["updates_seen"] == 3
    assert payload["messages_handled"] == 2
    assert payload["messages_denied"] == 1
    assert payload["next_offset"] == 13
    assert payload["stop_reason"] == "max_polls"
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_uses_stored_offset_when_offset_omitted(monkeypatch, tmp_path) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 1
        updates_seen = 0
        messages_handled = 0
        messages_denied = 0
        messages_ignored = 0
        next_offset = 100
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 99
            assert timeout == 1
            assert max_polls == 1
            return StubSummary()

    offset_file = tmp_path / "telegram.offset"
    offset_file.write_text("99\n")
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "1",
            "--offset-file",
            str(offset_file),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["offset_source"] == "store"
    assert payload["offset_file"] == str(offset_file)
    assert payload["offset_persistence_enabled"] is True
    assert payload["next_offset"] == 100
    assert "telegram-secret" not in result.stdout


def test_telegram_bot_run_explicit_offset_overrides_stored_offset(monkeypatch, tmp_path) -> None:
    from nutmeg.interfaces import cli as cli_module

    class StubSummary:
        polls_run = 1
        updates_seen = 0
        messages_handled = 0
        messages_denied = 0
        messages_ignored = 0
        next_offset = 11
        stop_reason = "max_polls"

    class StubDaemon:
        def run(self, *, offset: int | None, timeout: int, max_polls: int | None):
            assert offset == 10
            return StubSummary()

    offset_file = tmp_path / "telegram.offset"
    offset_file.write_text("99\n")
    monkeypatch.setenv("NUTMEG_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "111")
    clear_settings_cache()
    monkeypatch.setattr(
        cli_module,
        "build_telegram_polling_daemon",
        lambda settings, poll_interval_seconds, offset_store=None: StubDaemon(),
    )

    result = runner.invoke(
        app,
        [
            "telegram-bot-run",
            "--offset",
            "10",
            "--timeout",
            "1",
            "--poll-interval",
            "0",
            "--max-polls",
            "1",
            "--offset-file",
            str(offset_file),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["offset_source"] == "explicit"
    assert payload["next_offset"] == 11


def test_zucai_report_command_generates_json_artifacts_and_dry_run_dispatch(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    result = runner.invoke(
        app,
        [
            "zucai-report",
            "--issue-id",
            "26068",
            "--output-dir",
            str(tmp_path),
            "--pdf",
            "--dispatch-telegram",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["issue"]["issue_id"] == "26068"
    assert len(payload["recommendations"]) == 14
    assert payload["recommendations"][0]["pick"] == "31"
    assert payload["artifacts"]["pdf_path"].endswith(".pdf")
    assert payload["dispatch"]["status"] == "dry_run"
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")


def test_zucai_renjiu_daily_command_generates_three_tiers(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-renjiu-daily",
            "--date",
            "2026-04-26",
            "--issue-file",
            "nutmeg/zucai/samples/26068-issue.json",
            "--odds-file",
            "nutmeg/zucai/samples/26068-odds.json",
            "--output-dir",
            str(tmp_path),
            "--pdf",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["recommended_ticket_id"] == "main"
    assert [ticket["ticket_id"] for ticket in payload["tickets"]] == [
        "conservative",
        "main",
        "aggressive",
    ]
    assert payload["artifacts"]["pdf_path"].endswith("analysis.pdf")
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")

def test_zucai_report_command_rejects_invalid_issue(tmp_path) -> None:
    issue_file = tmp_path / "bad-issue.json"
    issue_file.write_text(
        json.dumps(
            {"issue_id": "bad", "matches": [{"match_no": 1, "home_team": "A", "away_team": "B"}]}
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["zucai-report", "--issue-file", str(issue_file), "--format", "json"],
    )

    assert result.exit_code == 2
    assert "exactly 14" in result.stdout


def test_zucai_grade_command_returns_plan_coverage(tmp_path) -> None:
    report_result = runner.invoke(
        app,
        [
            "zucai-report",
            "--issue-id",
            "26068",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    assert report_result.exit_code == 0
    report_payload = json.loads(report_result.stdout)

    grade_result = runner.invoke(
        app,
        [
            "zucai-grade",
            "--report-file",
            report_payload["artifacts"]["report_json_path"],
            "--outcomes-file",
            "nutmeg/zucai/samples/26068-outcomes.json",
            "--format",
            "json",
        ],
    )

    assert grade_result.exit_code == 0
    payload = json.loads(grade_result.stdout)
    assert payload["issue_id"] == "26068"
    assert len(payload["match_results"]) == 14
    assert any(plan["covered"] for plan in payload["plan_results"])


def test_zucai_auto_run_command_skips_no_issue(tmp_path) -> None:
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps({"entries": []}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "zucai-auto-run",
            "--date",
            "2026-04-27",
            "--slot",
            "afternoon",
            "--registry-file",
            str(registry_file),
            "--output-dir",
            str(tmp_path / "scheduled"),
            "--run-record-file",
            str(tmp_path / "records.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "skipped_no_issue"
    assert payload["dispatch"]["status"] == "skipped"
    assert payload["artifacts"]["pdf_path"] is None
    assert not (tmp_path / "records.json").exists()


def test_zucai_auto_run_command_generates_afternoon_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    result = runner.invoke(
        app,
        [
            "zucai-auto-run",
            "--date",
            "2026-04-26",
            "--slot",
            "afternoon",
            "--registry-file",
            "nutmeg/zucai/samples/scheduled-issues.json",
            "--output-dir",
            str(tmp_path / "scheduled"),
            "--run-record-file",
            str(tmp_path / "records.json"),
            "--dispatch-telegram",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert payload["issue_id"] == "26068"
    assert payload["slot_label"] == "16:00首版分析"
    assert payload["dispatch"]["status"] == "dry_run"
    assert "16:00首版分析" in payload["dispatch"]["caption"]
    assert payload["artifacts"]["pdf_path"].endswith(".pdf")
    assert Path(payload["artifacts"]["pdf_path"]).read_bytes().startswith(b"%PDF")
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert records[0]["slot"] == "afternoon"


def test_zucai_auto_run_command_duplicate_and_force(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "1234")
    base_args = [
        "zucai-auto-run",
        "--date",
        "2026-04-26",
        "--slot",
        "revision",
        "--registry-file",
        "nutmeg/zucai/samples/scheduled-issues.json",
        "--output-dir",
        str(tmp_path / "scheduled"),
        "--run-record-file",
        str(tmp_path / "records.json"),
        "--dispatch-telegram",
        "--dry-run",
        "--format",
        "json",
    ]

    first = runner.invoke(app, base_args)
    duplicate = runner.invoke(app, base_args)
    forced = runner.invoke(app, [*base_args, "--force"])

    assert first.exit_code == 0
    assert duplicate.exit_code == 0
    assert forced.exit_code == 0
    assert json.loads(first.stdout)["status"] == "dry_run"
    assert json.loads(duplicate.stdout)["status"] == "skipped_duplicate"
    assert json.loads(forced.stdout)["status"] == "dry_run"
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))["records"]
    assert len(records) == 2


def test_zucai_source_sync_command_generates_registry(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-source-sync",
            "--source-file",
            "nutmeg/zucai/samples/26068-source-notice.html",
            "--date",
            "2026-04-26",
            "--output-dir",
            str(tmp_path / "zucai"),
            "--registry-file",
            str(tmp_path / "zucai" / "issues.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["parsed_count"] == 1
    assert payload["active_issue_ids"] == ["26068"]
    assert Path(payload["written_issue_paths"]["26068"]).exists()
    registry = json.loads(Path(payload["registry_path"]).read_text(encoding="utf-8"))
    assert registry["entries"][0]["issue_id"] == "26068"


def test_zucai_source_sync_command_rejects_url_without_live_fetch(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "zucai-source-sync",
            "--source-url",
            "https://example.test/source.html",
            "--date",
            "2026-04-26",
            "--output-dir",
            str(tmp_path / "zucai"),
            "--registry-file",
            str(tmp_path / "zucai" / "issues.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    assert "requires --live-fetch" in result.stdout
