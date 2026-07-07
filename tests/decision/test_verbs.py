# tests/decision/test_verbs.py
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def test_decision_sense_command_registered():
    result = runner.invoke(app, ["decision-sense", "--help"])
    assert result.exit_code == 0
    assert "run-date" in result.output.lower() or "date" in result.output.lower()


def test_all_five_verbs_registered():
    result = runner.invoke(app, ["--help"])
    for verb in ["decision-sense", "decision-read", "decision-express",
                 "decision-reconcile", "decision-calibrate"]:
        assert verb in result.output


def test_run_sense_seeds_entities_even_without_snapshot(tmp_path):
    """run_sense 幂等落实体种子——read 时 Claude 能从 store 读联赛/球队画像。"""
    from nutmeg.decision.ontology import League
    from nutmeg.decision.store import DecisionStore
    from nutmeg.decision.verbs import run_sense
    run_sense("2026-07-08", tmp_path, "2026-07-08T08:00:00+08:00")
    store = DecisionStore(tmp_path / "decision")
    assert store.get(League, "swe-allsvenskan") is not None


def test_run_calibrate_panel_syncs_factor_scopes(tmp_path):
    """settle 的 calibrate 步自动纠偏 live store 的旧 scope 行(幂等挂钩)。"""
    from nutmeg.decision.ontology import Factor
    from nutmeg.decision.store import DecisionStore
    from nutmeg.decision.verbs import run_calibrate_panel
    store = DecisionStore(tmp_path / "decision")
    store.upsert(Factor.from_dict({
        "factor_id": "league_bias", "name_zh": "极端联赛画像", "definition": "d",
        "born_at": "2026-07-05", "born_from": "x", "status": "probation"}))
    run_calibrate_panel(tmp_path, "2026-07-07")
    assert store.get(Factor, "league_bias").scope == "league"
