import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_ingest_evidence_day_cli(tmp_path) -> None:
    avail = tmp_path / "avail.json"
    avail.write_text(json.dumps([{"match_no": "周日001", "team": "哈马比", "players": [
        {"name": "Striker A", "provider_id": "P-1", "availability": "out",
         "status_kind": "injury"}]}]), encoding="utf-8")
    runner.invoke(app, ["ontology", "init", "--format", "json"])
    result = runner.invoke(app, [
        "ontology", "ingest-evidence-day", "--business-date", "2026-07-19",
        "--availability", str(avail), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "person_statuses" in payload
    assert "skipped" in payload
