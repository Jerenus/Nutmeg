import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from tests.decision.crowd_fixtures import seed_history
from tests.decision.test_crowd_prereg import CR


def _setup(tmp_path: Path, *, n: int = 30) -> tuple[Path, Path]:
    data = tmp_path / "data"
    seed_history(data / "zucai", first=26001, n=n, gamma=-0.3)
    reg = tmp_path / "registry"
    reg.mkdir()
    doc = dict(CR, window={"issue_from": "26016", "issue_to": "26999"},
               replay_window={"issue_from": "26001", "issue_to": "26015"})
    (reg / "CR1.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(reg / "CR1.json"),
                                 "--data-dir", str(data)])
    assert r.exit_code == 0, r.output
    return data, reg


def test_rsi_grade_cr_replay_and_prospective(tmp_path):
    data, reg = _setup(tmp_path)
    for mode, n in (("replay", 15), ("prospective", 15)):
        r = CliRunner().invoke(app, ["rsi", "grade", "--exp", "CR1", "--mode", mode,
                                     "--registry-dir", str(reg), "--data-dir", str(data)])
        assert r.exit_code == 0, r.output
        assert f"CR1 [{mode}] n={n}" in r.output


def test_rsi_grade_cr_refuses_edited_registry_doc(tmp_path):
    data, reg = _setup(tmp_path)
    doc = json.loads((reg / "CR1.json").read_text("utf-8"))
    doc["trigger"] = {"field": "face", "op": "==", "v": "3"}
    (reg / "CR1.json").write_text(json.dumps(doc), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "grade", "--exp", "CR1", "--mode", "replay",
                                 "--registry-dir", str(reg), "--data-dir", str(data)])
    assert r.exit_code != 0 and "冻结指纹" in r.output
