import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_load_ledger_previews_without_writing_and_writes_with_flag(tmp_path: Path):
    _write(tmp_path / "zucai" / "26136-issue.json", {
        "issue_id": "26136", "sale_deadline": "2026-10-09 22:00", "matches": [
            {"match_no": 3, "home_team": "丙", "away_team": "丁",
             "kickoff_bj": "2026-10-10 00:30"}]})
    preview = runner.invoke(app, ["load", "ledger", "--issue", "26136",
                                  "--data-dir", str(tmp_path)])
    assert preview.exit_code == 0, preview.output
    assert "丙-丁" in preview.output and "预览" in preview.output
    assert not (tmp_path / "zucai" / "26136-team-load.json").exists()

    written = runner.invoke(app, ["load", "ledger", "--issue", "26136", "--write",
                                  "--data-dir", str(tmp_path)])
    assert written.exit_code == 0, written.output
    assert (tmp_path / "zucai" / "26136-team-load.json").exists()


def test_load_ledger_needs_day_or_issue(tmp_path: Path):
    out = runner.invoke(app, ["load", "ledger", "--data-dir", str(tmp_path)])
    assert out.exit_code != 0
