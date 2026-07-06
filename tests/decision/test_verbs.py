# tests/decision/test_verbs.py
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_decision_sense_command_registered():
    result = runner.invoke(app, ["decision-sense", "--help"])
    assert result.exit_code == 0
    assert "run-date" in result.output.lower() or "date" in result.output.lower()


def test_all_five_verbs_registered():
    result = runner.invoke(app, ["--help"])
    for verb in ["decision-sense", "decision-read", "decision-express",
                 "decision-reconcile", "decision-calibrate"]:
        assert verb in result.output
