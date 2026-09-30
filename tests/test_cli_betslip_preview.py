import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def _legs(tmp_path: Path, name: str, legs: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(legs), encoding="utf-8")
    return path


def test_preview_shows_the_diagnosis_without_registering(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    fair = {"home": 0.357, "draw": 0.270, "away": 0.373}
    turkey = {"key": "周一004", "market": "had", "selections": ["home"], "odds": [2.58],
              "fair": fair}
    first = _legs(tmp_path, "j1.json", [turkey, {"key": "周一007", "market": "had",
                                                  "selections": ["home"], "odds": [1.82]}])
    reg = runner.invoke(app, ["betslip", "register", "--slip-id", "J1", "--channel", "jczq",
                              "--placed-at", "2026-09-28", "--legs-file", str(first),
                              "--combo", "2", "--data-dir", str(data)])
    assert reg.exit_code == 0, reg.output
    second = _legs(tmp_path, "j2.json", [turkey, {"key": "周一005", "market": "had",
                                                   "selections": ["home"], "odds": [3.77]}])
    pre = runner.invoke(app, ["betslip", "preview", "--channel", "jczq",
                              "--placed-at", "2026-09-28", "--legs-file", str(second),
                              "--combo", "2", "--multiplier", "50", "--data-dir", str(data)])
    assert pre.exit_code == 0, pre.output
    assert "预览 jczq 1 注 × 50 倍 = ¥100" in pre.output
    assert "共享裸单 1 条（周一0043）与 1 张票同押；这些票一起死 ≥64%" in pre.output
    rows = (data / "betslips.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["slip_id"] == "J1"
