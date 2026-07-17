from types import SimpleNamespace

from typer.testing import CliRunner

import nutmeg.interfaces.cli as cli
from nutmeg.interfaces.cli import app

runner = CliRunner()


class FakeReportService:
    def build_report(self, **kwargs):
        return SimpleNamespace(
            dispatch=SimpleNamespace(status="failed"),
            to_dict=lambda: {"dispatch": {"status": "failed"}},
        )


class FakeScheduledService:
    def run(self, **kwargs):
        return SimpleNamespace(
            dispatch=SimpleNamespace(status="partial"),
            status="partial",
            to_dict=lambda: {
                "status": "partial",
                "dispatch": {"status": "partial"},
            },
        )


def test_zucai_report_json_exits_nonzero_on_required_delivery_failure(monkeypatch) -> None:
    monkeypatch.setattr(cli, "build_zucai_workflow_service", FakeReportService)

    result = runner.invoke(
        app,
        [
            "zucai-report",
            "--issue-id",
            "26068",
            "--dispatch-telegram",
            "--no-dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    assert '"status": "failed"' in result.output


def test_zucai_auto_run_json_exits_nonzero_on_partial_delivery(monkeypatch) -> None:
    monkeypatch.setattr(cli, "build_zucai_scheduled_delivery_service", FakeScheduledService)

    result = runner.invoke(
        app,
        [
            "zucai-auto-run",
            "--slot",
            "afternoon",
            "--dispatch-telegram",
            "--no-dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    assert '"status": "partial"' in result.output
