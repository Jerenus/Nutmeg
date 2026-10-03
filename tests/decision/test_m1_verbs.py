
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_decision_read_routes_to_kernel_adapter(tmp_path, monkeypatch):
    import nutmeg.decision.ontology_adapter as ontology_adapter

    seen: dict = {}

    def _fake(reads_file, output_dir):
        seen.update(reads_file=reads_file, output_dir=output_dir)
        return "摄取 1 条"

    monkeypatch.setattr(ontology_adapter, "run_decision_read_v2", _fake)
    reads_file = tmp_path / "reads.json"
    reads_file.write_text("[]", encoding="utf-8")
    result = runner.invoke(app, [
        "decision-read", "--reads-file", str(reads_file),
        "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "摄取" in result.output
    assert seen["reads_file"] == reads_file


def test_decision_capture_closing_registered():
    result = runner.invoke(app, ["decision-capture-closing", "--help"])
    assert result.exit_code == 0
