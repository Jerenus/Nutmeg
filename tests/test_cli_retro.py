import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_retro_encode_reports_missing_inputs_instead_of_inventing_them(tmp_path: Path):
    result = runner.invoke(app, ["retro", "encode", "--date", "2026-09-28", "--issue", "26134",
                                 "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["jczq"]["status"] == "no_results" and out["zucai"]["status"] == "no_official_draw"
    assert runner.invoke(app, ["retro", "encode", "--data-dir", str(tmp_path)]).exit_code == 1
