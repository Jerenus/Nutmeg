import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()

_SPORTTERY = {"matchInfoList": [{"businessDate": "2026-07-19", "subMatchList": [
    {"matchStatus": "Selling", "businessDate": "2026-07-19", "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": "2026-07-19", "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
_BOLD = {"周日001": {"match_winner": {"odds": {"home": 2.05, "draw": 3.40, "away": 3.20}}}}


def test_ingest_market_day_cli_reports_counts(tmp_path) -> None:
    sporttery = tmp_path / "sporttery.json"
    intl = tmp_path / "bold.json"
    sporttery.write_text(json.dumps(_SPORTTERY), encoding="utf-8")
    intl.write_text(json.dumps(_BOLD), encoding="utf-8")
    init = runner.invoke(app, ["ontology", "init", "--format", "json"])
    result = runner.invoke(app, [
        "ontology", "ingest-market-day", "--business-date", "2026-07-19",
        "--sporttery", str(sporttery), "--intl", str(intl), "--format", "json",
    ])
    assert init.exit_code == 0
    assert result.exit_code == 0
    assert json.loads(result.stdout)["matches"] == 1
