import json
from pathlib import Path

from typer.testing import CliRunner

import nutmeg.config.settings as settings_module
from nutmeg.config.settings import AppSettings
from nutmeg.decision.ontology_adapter import run_decision_am_v2
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-19"
SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": DATE, "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
BOLD = {"周日001": {"match_winner": {"odds": {"home": 2.05, "draw": 3.40, "away": 3.20}}}}


def _write_snapshots(output_dir: Path) -> None:
    day = output_dir / "daily" / DATE
    day.mkdir(parents=True)
    (day / "sporttery_markets.json").write_text(json.dumps(SPORTTERY), encoding="utf-8")
    (day / "bold_odds.json").write_text(json.dumps(BOLD), encoding="utf-8")


def test_am_v2_ingests_into_kernel(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    _write_snapshots(output_dir)
    result = run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False)
    assert result.succeeded
    assert "入库 1 场" in str(result)
    assert kernel.status().match_count == 1


def test_am_v2_empty_board_is_legal(tmp_path: Path) -> None:
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    result = run_decision_am_v2(DATE, tmp_path / "jczq", kernel=kernel, fetch=False)
    assert result.succeeded and "空盘" in str(result)
    assert kernel.status().match_count == 0


def test_flag_routes_am_to_v2(tmp_path: Path, monkeypatch) -> None:
    import nutmeg.interfaces.cli as cli

    calls = {"v2": 0, "old": 0}

    def fake_v2(run_date, output_dir, **kwargs):
        calls["v2"] += 1
        from nutmeg.decision.verbs import DecisionWorkflowResult
        return DecisionWorkflowResult("decision-am", run_date, (), "v2")

    monkeypatch.setattr("nutmeg.decision.ontology_adapter.run_decision_am_v2", fake_v2)
    monkeypatch.setenv("NUTMEG_ONTOLOGY_V2", "1")
    settings_module.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, [
            "decision-am", "--run-date", DATE, "--output-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert calls["v2"] == 1               # flag on -> routed to the kernel adapter
    finally:
        settings_module.get_settings.cache_clear()


def test_unset_flag_keeps_old_path(tmp_path: Path, monkeypatch) -> None:
    import nutmeg.interfaces.cli as cli

    seen = {"old": 0}

    def fake_old(run_date, output_dir, **kwargs):
        seen["old"] += 1
        from nutmeg.decision.verbs import DecisionWorkflowResult
        return DecisionWorkflowResult("decision-am", run_date, (), "old")

    monkeypatch.setattr("nutmeg.decision.verbs.run_decision_am", fake_old)
    monkeypatch.delenv("NUTMEG_ONTOLOGY_V2", raising=False)
    settings_module.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, [
            "decision-am", "--run-date", DATE, "--output-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert seen["old"] == 1                # flag off -> old JSONL path unchanged
    finally:
        settings_module.get_settings.cache_clear()
