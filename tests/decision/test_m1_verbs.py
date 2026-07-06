import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_decision_read_ingests_from_json_file(tmp_path):
    reads_file = tmp_path / "reads.json"
    reads_file.write_text(json.dumps([{
        "read_id": "R-1", "match_id": "M-2026-07-08-周日092", "snapshot_id": "S-1",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.42, "draw": 0.28, "away": 0.30},
        "belief": {"home": 0.42, "draw": 0.28, "away": 0.30},
        "factors": [], "confidence": 1, "shadow": True}]), encoding="utf-8")
    result = runner.invoke(app, [
        "decision-read", "--reads-file", str(reads_file),
        "--output-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "摄取" in result.output or "ingest" in result.output.lower()
    from nutmeg.decision.ontology import Read
    from nutmeg.decision.store import DecisionStore
    assert DecisionStore(tmp_path / "decision").get(Read, "R-1") is not None


def test_decision_capture_closing_registered():
    result = runner.invoke(app, ["decision-capture-closing", "--help"])
    assert result.exit_code == 0
