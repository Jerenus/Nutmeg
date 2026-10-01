import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from tests.gym.test_board import DAY, _jczq_day, _zucai_issue


def _data(tmp_path: Path) -> Path:
    data = _jczq_day(tmp_path)
    _zucai_issue(tmp_path)
    results = json.loads((data / "jczq" / "jc-results.json").read_text(encoding="utf-8"))
    results[DAY]["周六002"] = {"match_id": "2", "ft_home": 0, "ft_away": 1}
    (data / "jczq" / "jc-results.json").write_text(json.dumps(results), encoding="utf-8")
    return data


def test_gym_run_prints_the_policy_table_and_writes_outputs(tmp_path: Path) -> None:
    data = _data(tmp_path)
    out = tmp_path / "run1"
    result = CliRunner().invoke(app, ["gym", "run", "--policy", "flat,jczq_max_p,zucai_max_p",
                                      "--data-dir", str(data), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "| flat | 0 |" in result.output and "| jczq_max_p |" in result.output
    assert (out / "report.md").exists() and (out / "ledger.jsonl").exists()


def test_gym_run_rejects_unknown_policy(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["gym", "run", "--policy", "nope", "--data-dir",
                                      str(_data(tmp_path))])
    assert result.exit_code == 2 and "未登记的策略" in result.output


def test_gym_verify_compares_real_slips_with_the_scoreboard(tmp_path: Path) -> None:
    data = _data(tmp_path)
    (data / "betslips.jsonl").write_text(json.dumps({
        "slip_id": "20260920-J1", "channel": "jczq", "placed_at": DAY, "purchased": True,
        "legs": [{"key": "周六001", "name": "x", "market": "had", "line": None,
                  "selections": ["home"], "odds": [1.85]},
                 {"key": "周六002", "name": "y", "market": "had", "line": None,
                  "selections": ["away"], "odds": [3.9]}], "combo_sizes": [2], "multiplier": 1,
    }) + "\n", encoding="utf-8")
    payout = round(1.85 * 3.9 * 2, 2)
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "jczq-20260920": {"net": round(payout - 2, 2), "stake": 2}}}), encoding="utf-8")

    ok = CliRunner().invoke(app, ["gym", "verify", "--data-dir", str(data)])
    assert ok.exit_code == 0, ok.output
    assert "| jczq-20260920 |" in ok.output and "可比键总差 +0" in ok.output

    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "jczq-20260920": {"net": -2, "stake": 2}}}), encoding="utf-8")
    bad = CliRunner().invoke(app, ["gym", "verify", "--data-dir", str(data)])
    assert bad.exit_code == 1
