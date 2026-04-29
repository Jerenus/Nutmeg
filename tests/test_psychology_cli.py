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


def test_inspiration_write_creates_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_INSPIRATION_DIR", str(tmp_path))
    monkeypatch.setenv("NUTMEG_PSYCHOLOGY_PARSER_FAKE_MODE", "1")
    runner = CliRunner()
    result = runner.invoke(app, ["inspiration-write", "--date", "20260429", "--text", "今晚反着来，淘汰赛"])
    assert result.exit_code == 0, result.output
    raw = (tmp_path / "2026-04-29" / "raw.md").read_text(encoding="utf-8")
    assert "反着来" in raw
    parsed = json.loads((tmp_path / "2026-04-29" / "parsed.json").read_text(encoding="utf-8"))
    assert parsed["parsed_tags"]["lean"] == "psychology"
    assert "tournament_stage" in parsed["parsed_tags"]["focus"]


def test_inspiration_show_prints_parsed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NUTMEG_INSPIRATION_DIR", str(tmp_path))
    monkeypatch.setenv("NUTMEG_PSYCHOLOGY_PARSER_FAKE_MODE", "1")
    runner = CliRunner()
    runner.invoke(app, ["inspiration-write", "--date", "20260429", "--text", "反着来"])
    result = runner.invoke(app, ["inspiration-show", "20260429"])
    assert result.exit_code == 0
    assert "psychology" in result.output
