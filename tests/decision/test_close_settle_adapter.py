import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.decision.ontology_adapter import (
    run_decision_am_v2,
    run_decision_close_v2,
    run_decision_express_v2,
    run_decision_read_v2,
    run_decision_settle_v2,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

DATE = "2026-07-19"
PRIOR = {"home": 0.5, "draw": 0.3, "away": 0.2}
SPORTTERY = {"matchInfoList": [{"businessDate": DATE, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DATE, "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": DATE, "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
BOLD = {"周日001": {"match_winner": {"odds": {"home": 2.05, "draw": 3.40, "away": 3.20}}}}


def _kernel_with_read(tmp_path: Path):
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp_path / "data"))
    kernel.initialize()
    output_dir = tmp_path / "jczq"
    day = output_dir / "daily" / DATE
    day.mkdir(parents=True)
    (day / "sporttery_markets.json").write_text(json.dumps(SPORTTERY), encoding="utf-8")
    (day / "bold_odds.json").write_text(json.dumps(BOLD), encoding="utf-8")
    run_decision_am_v2(DATE, output_dir, kernel=kernel, fetch=False)
    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
    reads = [{"read_id": "r1", "match_id": match_id, "market": "had",
              "prior": PRIOR, "belief": PRIOR, "factors": [],
              "made_at": "2026-07-19T15:00:00+08:00"}]
    (day / "reads.json").write_text(json.dumps(reads), encoding="utf-8")
    run_decision_read_v2(day / "reads.json", output_dir, kernel=kernel)
    return kernel, match_id, output_dir


def _write_legs(output_dir: Path, legs: list) -> Path:
    path = output_dir / "daily" / DATE / "legs.json"
    path.write_text(json.dumps(legs), encoding="utf-8")
    return path


def test_express_v2_books_ticket_within_budget(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_read(tmp_path)
    legs = [{"match_id": match_id, "market": "had", "selection": "home",
             "odds": 2.10, "bucket": "main"}]
    msg = run_decision_express_v2(_write_legs(output_dir, legs), output_dir, kernel=kernel)
    assert "1 票" in msg
    assert kernel.status().ticket_count == 1
    with OntologyUnitOfWork(kernel.engine) as uow:
        balance = uow.finance.ledger_balance("acct-jczq")
        [ticket_id] = uow.finance.tickets_for_match(match_id)
        [row] = uow.finance.bet_legs_for(ticket_id)
    assert balance < 0                          # stake debited
    assert row.match_id == match_id             # leg references the ingested match
    assert row.forecast_revision_id            # and the committed Read


def test_express_v2_books_hhad_leg_with_line(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_read(tmp_path)
    # a committed hhad read + an hhad leg carrying a handicap line
    reads = [{"read_id": "rh", "match_id": match_id, "market": "hhad",
              "prior": PRIOR, "belief": PRIOR, "factors": [],
              "made_at": "2026-07-19T15:00:00+08:00"}]
    (output_dir / "daily" / DATE / "reads_hhad.json").write_text(json.dumps(reads),
                                                                 encoding="utf-8")
    run_decision_read_v2(output_dir / "daily" / DATE / "reads_hhad.json", output_dir,
                         kernel=kernel)
    legs = [{"match_id": match_id, "market": "hhad", "selection": "home", "line": "-1",
             "odds": 2.0, "bucket": "hedge"}]
    msg = run_decision_express_v2(_write_legs(output_dir, legs), output_dir, kernel=kernel)
    assert "1 票" in msg                          # line lives on the leg, not the selection
    with OntologyUnitOfWork(kernel.engine) as uow:
        [ticket_id] = uow.finance.tickets_for_match(match_id)
        [row] = uow.finance.bet_legs_for(ticket_id)
    assert row.line == "-1"                        # the handicap is preserved on the leg


def test_express_v2_skips_leg_without_read(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_read(tmp_path)
    legs = [{"match_id": match_id, "market": "ttg", "selection": "total_2",
             "odds": 3.0, "bucket": "main"}]   # no committed ttg read
    msg = run_decision_express_v2(_write_legs(output_dir, legs), output_dir, kernel=kernel)
    assert "0 票" in msg and "跳过 1" in msg
    assert kernel.status().ticket_count == 0


def test_empty_legs_is_empty_slate(tmp_path: Path) -> None:
    kernel, _match_id, output_dir = _kernel_with_read(tmp_path)
    msg = run_decision_express_v2(_write_legs(output_dir, []), output_dir, kernel=kernel)
    assert "0 票" in msg and "空仓合法" in msg
    assert kernel.status().ticket_count == 0


def test_manual_legs_file_cannot_drive_close_without_ontology_terminal(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_read(tmp_path)
    _write_legs(
        output_dir,
        [
            {
                "match_id": match_id,
                "market": "had",
                "selection": "home",
                "odds": 2.10,
                "bucket": "main",
            }
        ],
    )

    result = run_decision_close_v2(DATE, output_dir, kernel=kernel)

    assert not result.succeeded
    assert "terminal decision is missing" in str(result)
    assert kernel.status().ticket_count == 0


def test_settle_v2_settles_and_calibrates(tmp_path: Path) -> None:
    kernel, match_id, output_dir = _kernel_with_read(tmp_path)
    legs = [{"match_id": match_id, "market": "had", "selection": "home",
             "odds": 2.10, "bucket": "main"}]
    run_decision_express_v2(_write_legs(output_dir, legs), output_dir, kernel=kernel)
    with OntologyUnitOfWork(kernel.engine) as uow:
        staked = uow.finance.ledger_balance("acct-jczq")       # negative
    # home wins -> the had-home ticket wins
    (output_dir / "daily" / DATE / "results.json").write_text(
        json.dumps({match_id: "home"}), encoding="utf-8")

    result = run_decision_settle_v2(DATE, output_dir, kernel=kernel)
    assert result.succeeded
    status = kernel.status()
    assert status.settlement_count == 1
    assert status.scorecard_count >= 3                          # calibrate ran
    with OntologyUnitOfWork(kernel.engine) as uow:
        assert uow.finance.ledger_balance("acct-jczq") > staked  # payout raised the ledger


def test_flag_routes_close_and_settle(tmp_path: Path, monkeypatch) -> None:
    import nutmeg.config.settings as settings_module
    import nutmeg.interfaces.cli as cli
    from nutmeg.decision.verbs import DecisionWorkflowResult

    hit = {"close": 0, "settle": 0}
    monkeypatch.setattr(
        "nutmeg.decision.ontology_adapter.run_decision_close_v2",
        lambda rd, od, **k: (hit.__setitem__("close", 1)
                             or DecisionWorkflowResult("decision-close", rd, (), "v2")))
    monkeypatch.setattr(
        "nutmeg.decision.ontology_adapter.run_decision_settle_v2",
        lambda rd, od, **k: (hit.__setitem__("settle", 1)
                             or DecisionWorkflowResult("decision-settle", rd, (), "v2")))
    monkeypatch.setenv("NUTMEG_ONTOLOGY_V2", "1")
    settings_module.get_settings.cache_clear()
    try:
        runner = CliRunner()
        assert runner.invoke(cli.app, ["decision-close", "--run-date", DATE,
                                       "--output-dir", str(tmp_path)]).exit_code == 0
        assert runner.invoke(cli.app, ["decision-settle", "--run-date", DATE,
                                       "--output-dir", str(tmp_path)]).exit_code == 0
        assert hit == {"close": 1, "settle": 1}   # flag on -> both money verbs routed to v2
    finally:
        settings_module.get_settings.cache_clear()
