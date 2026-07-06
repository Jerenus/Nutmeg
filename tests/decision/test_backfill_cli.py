"""decision-backfill CLI:未判场补市场基线 shadow。"""
import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨", "awayTeamAbbName": "英",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}}]}]}


def test_decision_backfill_shadows_unjudged(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")

    class _MO:
        def __init__(self, fair):
            self.fair_probability = fair
            self.line = None

    import nutmeg.decision.sense as sense_mod

    def _fake_euro(rd, od):
        return {"周日092": {"match_winner": _MO({"home": 0.42, "draw": 0.28, "away": 0.30})}}

    monkeypatch.setattr(sense_mod, "_load_euro_bold_odds", _fake_euro)
    runner.invoke(app, ["decision-sense", "--run-date", "2026-07-08",
                        "--output-dir", str(tmp_path), "--taken-at", "t"])
    result = runner.invoke(app, ["decision-backfill", "--run-date", "2026-07-08",
                                 "--output-dir", str(tmp_path), "--made-at", "t2"])
    assert result.exit_code == 0 and "1" in result.output
    from nutmeg.decision.ontology import Read
    from nutmeg.decision.store import DecisionStore
    reads = DecisionStore(tmp_path / "decision").load(Read)
    assert len(reads) == 1 and reads[0].shadow is True
