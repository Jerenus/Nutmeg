import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()

SIMPLE_PAYLOAD = {
    "issue": "X",
    "budget_yuan": 2,
    "fair": {"1": {"home": 0.5, "draw": 0.3, "away": 0.2}},
    "versions": [{"id": "A", "faces": {"1": "3"}}],
}


def _write_payload(tmp_path, payload) -> str:
    path = tmp_path / "optimizer.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    return str(path)


def test_zucai_optimize_json_output(tmp_path) -> None:
    input_file = _write_payload(tmp_path, SIMPLE_PAYLOAD)

    result = runner.invoke(app, ["zucai-optimize", "--input-file", input_file, "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["issue"] == "X"
    assert payload["best_within_cap_id"] == "A"
    assert payload["versions"][0]["p_all"] == 0.5


def test_zucai_optimize_text_table(tmp_path) -> None:
    input_file = _write_payload(tmp_path, SIMPLE_PAYLOAD)

    result = runner.invoke(app, ["zucai-optimize", "--input-file", input_file])

    assert result.exit_code == 0
    assert "足彩候选比较（X）" in result.stdout
    assert "版本" in result.stdout
    assert "P(全对)" in result.stdout
    assert "A" in result.stdout
    assert "帽内第一: A" in result.stdout


def test_zucai_optimize_bad_structure_exits_two(tmp_path) -> None:
    input_file = _write_payload(tmp_path, {})

    result = runner.invoke(app, ["zucai-optimize", "--input-file", input_file])

    assert result.exit_code == 2
    assert "输入错误" in result.stderr


def test_zucai_optimize_malformed_json_exits_two(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{", "utf-8")

    result = runner.invoke(app, ["zucai-optimize", "--input-file", str(path)])

    assert result.exit_code == 2
    assert "输入错误" in result.stderr


def test_zucai_optimize_help_lists_contract_options() -> None:
    result = runner.invoke(app, ["zucai-optimize", "--help"])

    assert result.exit_code == 0
    assert "--input-file" in result.stdout
    assert "--json" in result.stdout
