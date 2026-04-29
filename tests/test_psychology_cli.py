from __future__ import annotations

import json
from pathlib import Path
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app


def test_psychology_inspect_outputs_json(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps({"id": "f1", "competition_code": "UCL", "stage": "knockout", "leg": 1, "tier_home": 1, "tier_away": 1, "aggregate_score_diff": None, "home_team_name": "PSG", "away_team_name": "Bayern"}), encoding="utf-8")
    result = runner.invoke(app, ["psychology-inspect", "--fixture-file", str(fixture_path), "--rules-only"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["fixture_id"] == "f1"
    assert "tournament_stage" in {r["provider"] for r in payload["readings"]}
