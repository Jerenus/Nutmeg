import json
from pathlib import Path

from nutmeg.decision.account import exploration_spend, month_report, render_month


def _data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "zucai").mkdir(parents=True)
    (data / "zucai" / "26135-issue.json").write_text(
        json.dumps({"issue_id": "26135", "sale_deadline": "2026-10-03 21:00"}), encoding="utf-8")
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "jczq-20261002": {"net": -120, "stake": 200},
        "26135": {"net": 300, "stake": 100},
        "jczq-20260928": {"net": -350, "stake": 350},
    }}), encoding="utf-8")
    (data / "betslips.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"slip_id": "E1", "channel": "jczq", "placed_at": "2026-10-02", "purchased": True,
         "note": "EXP:G1 热门两两", "stake_yuan": 6, "legs": []},
        {"slip_id": "E2", "channel": "jczq", "placed_at": "2026-10-03", "purchased": False,
         "note": "EXP:G1", "stake_yuan": 6, "legs": []},
        {"slip_id": "J1", "channel": "jczq", "placed_at": "2026-10-02", "purchased": True,
         "note": "", "stake_yuan": 100, "legs": []},
    ]) + "\n", encoding="utf-8")
    return data


def test_month_report_splits_channels_and_counts_exploration(tmp_path: Path, monkeypatch) -> None:
    data = _data(tmp_path)
    monkeypatch.setattr("nutmeg.decision.account.experiment_board",
                        lambda _d: {"F14": {"layer": "judgment", "tier": "observation", "n": 12,
                                            "n_min": 60, "metric_pp": 4.2, "ci": [-1.0, 9.4],
                                            "verdict": None},
                                    "G1": {"layer": "structural", "tier": "observation", "n": 100,
                                           "n_min": 100, "metric_pp": -12.0, "ci": [-20.0, -6.0],
                                           "verdict": "falsified"}})
    report = month_report(data, "2026-10")
    assert report["net"] == 180.0 and report["by_channel"] == {"jczq": -120.0, "zucai": 300.0}
    assert report["tripped"] is False and report["entries"] == 2
    assert report["exploration"]["stake"] == 6.0 and len(report["exploration"]["slips"]) == 1
    assert report["verdicts"] == {"not_due": 1, "falsified": 1}
    text = render_month(report)
    assert "净值 vs 空仓**：+180" in text and "竞彩 -120 / 足彩 +300" in text
    assert "| G1（主） | structural | 100 / 100 | -12.0 | [-20.0, -6.0] | falsified |" in text
    assert "falsified 1" in text and "EXP 票，¥6" in text


def test_exploration_spend_ignores_other_months_and_trials(tmp_path: Path) -> None:
    data = _data(tmp_path)
    assert exploration_spend(data, "2026-09") == {"slips": [], "stake": 0.0}
    [row] = exploration_spend(data, "2026-10")["slips"]
    assert row["exp"] == "G1" and row["slip_id"] == "E1"


def test_month_report_marks_tripped_brake(tmp_path: Path, monkeypatch) -> None:
    data = _data(tmp_path)
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "jczq-20261002": {"net": -3200, "stake": 3300}}}), encoding="utf-8")
    monkeypatch.setattr("nutmeg.decision.account.experiment_board", lambda _d: {})
    report = month_report(data, "2026-10")
    assert report["tripped"] is True and "⛔已触发" in render_month(report)


def test_deviation_ledger_groups_purchased_slips_by_reason_and_joins_payouts(tmp_path: Path,
                                                                             monkeypatch) -> None:
    from nutmeg.decision.account import deviation_ledger

    data = _data(tmp_path)
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "26135": {"net": -64, "stake": 64, "slips": [{"id": "D1", "stake": 64, "payout": 0.0}]},
        "jczq-20261002": {"net": 100, "stake": 50,
                          "slips": [{"id": "D2", "stake": 50, "payout": 150.0}]},
        "26131": {"net": -10, "stake": 10, "slips": ["R9-1 文字描述的旧条目"]},
        "note": "非 dict 的旧条目"}}),
        encoding="utf-8")
    (data / "betslips.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"slip_id": "D1", "channel": "renjiu", "placed_at": "2026-10-03", "purchased": True,
         "issue": "26135", "faces": {str(i): "3" for i in range(1, 10)}, "legs": [],
         "deviation": "price_instinct", "prediction": "场2 客队不会输"},
        {"slip_id": "D2", "channel": "jczq", "placed_at": "2026-10-02", "purchased": True,
         "legs": [], "deviation": "fact_self_judged", "prediction": ""},
        {"slip_id": "D3", "channel": "jczq", "placed_at": "2026-10-02", "purchased": True,
         "legs": [], "deviation": "fact_self_judged"},
        {"slip_id": "T1", "channel": "jczq", "placed_at": "2026-10-02", "purchased": False,
         "legs": [], "deviation": "other"},
        {"slip_id": "N1", "channel": "jczq", "placed_at": "2026-10-02", "purchased": True,
         "legs": []},
    ]) + "\n", encoding="utf-8")
    led = deviation_ledger(data, "2026-10")
    assert led["n"] == 3
    assert led["by_reason"]["price_instinct"]["net"] == -64.0
    assert led["by_reason"]["price_instinct"]["predictions"] == ["D1: 场2 客队不会输"]
    fact = led["by_reason"]["fact_self_judged"]
    assert fact["n"] == 2 and fact["pending"] == 1 and fact["payout"] == 150.0
    monkeypatch.setattr("nutmeg.decision.account.experiment_board", lambda _d: {})
    text = render_month(month_report(data, "2026-10"))
    assert "人的偏离" in text and "price_instinct：1 张 投入 ¥64 净 -64" in text



def test_previous_month_handles_january_and_the_cli_flag(tmp_path: Path, monkeypatch) -> None:
    from datetime import date

    from typer.testing import CliRunner

    from nutmeg.decision.account import previous_month
    from nutmeg.interfaces.cli import app

    assert previous_month(date(2026, 10, 1)) == "2026-09"
    assert previous_month(date(2027, 1, 1)) == "2026-12"
    data = _data(tmp_path)
    monkeypatch.setattr("nutmeg.decision.account.experiment_board", lambda _d: {})
    monkeypatch.setattr("nutmeg.decision.account.previous_month", lambda today=None: "2026-10")
    out = CliRunner().invoke(app, ["account", "month", "--previous", "--write",
                                   "--data-dir", str(data)])
    assert out.exit_code == 0, out.output
    assert (data / "analytics" / "account" / "2026-10.md").exists()
    both = CliRunner().invoke(app, ["account", "month", "--previous", "--month", "2026-09",
                                    "--data-dir", str(data)])
    assert both.exit_code == 2


def test_rule_v3_board_replays_the_month_and_renders_three_rows(tmp_path: Path,
                                                                monkeypatch) -> None:
    from types import SimpleNamespace

    from nutmeg.decision import account

    calls: list = []

    def fake_run_gym(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(per_policy={
            "real": {"slips": 26, "stake": 1886, "net": -1508.5, "roi": -0.7998, "keys": 7},
            "jczq_rule_v3": {"slips": 9, "stake": 18, "net": -18.0, "roi": -1.0, "keys": 9},
            "flat": {"slips": 0, "stake": 0, "net": 0.0, "roi": 0.0, "keys": 0}})

    monkeypatch.setattr("nutmeg.gym.board.list_days",
                        lambda data_dir: ["2026-08-31", "2026-09-01", "2026-09-02"])
    monkeypatch.setattr("nutmeg.gym.run.run_gym", fake_run_gym)
    board = account.rule_v3_board(tmp_path, "2026-09")
    assert calls[0]["days"] == ["2026-09-01", "2026-09-02"] and calls[0]["issues"] == []
    assert calls[0]["ctx"].belief_source == "read"
    assert board["jczq_rule_v3"]["net"] == -18.0 and board["days"] == 2

    monkeypatch.setattr("nutmeg.decision.account.experiment_board", lambda _d: {})
    monkeypatch.setattr("nutmeg.decision.account.rule_v3_board", lambda _d, _m: board)
    text = account.render_month(account.month_report(tmp_path, "2026-09"))
    assert "| 规则 v3 | 9 | 9 | 18 | -18 | -100.0% |" in text
    assert "| 实际出票 | 26 | 7 | 1,886 | -1,508 | -80.0% |" in text


def test_rule_v3_board_reports_a_replay_failure_instead_of_crashing(tmp_path: Path,
                                                                    monkeypatch) -> None:
    from nutmeg.decision import account

    def boom(data_dir):
        raise RuntimeError("no boards")

    monkeypatch.setattr("nutmeg.gym.board.list_days", boom)
    assert "_error" in account.rule_v3_board(tmp_path, "2026-09")


def test_late_reasons_and_vetoed_purchases_get_their_own_lines(tmp_path: Path,
                                                               monkeypatch) -> None:
    """2026-10-06：开球后才写的理由不进按理由的净值；审票否决仍买单独记账。"""
    from nutmeg.decision.account import deviation_ledger, vetoed_ledger

    data = _data(tmp_path)
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {"26135": {
        "net": -300, "stake": 300, "slips": [{"id": "A", "stake": 100, "payout": 0.0},
                                             {"id": "B", "stake": 200, "payout": 0.0}]}}}),
        encoding="utf-8")
    common = {"channel": "renjiu", "placed_at": "2026-10-05", "purchased": True,
              "issue": "26135", "faces": {str(i): "3" for i in range(1, 10)}, "legs": [],
              "first_kickoff": "2026-10-06T00:00:00+08:00"}
    (data / "betslips.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {**common, "slip_id": "A", "deviation": "price_instinct",
         "deviation_at": "2026-10-05T20:00:00+08:00",
         "diagnosis": {"review": {"vetoed": True, "codes": ["V2"], "ratio": 0.7}}},
        {**common, "slip_id": "B", "deviation": "price_instinct",
         "deviation_at": "2026-10-06T09:00:00+08:00",
         "diagnosis": {"review": {"vetoed": False, "codes": [], "ratio": 0.9}}},
        {**common, "slip_id": "C", "diagnosis": {}},
    ]) + "\n", encoding="utf-8")
    led = deviation_ledger(data, "2026-10")
    assert led["n"] == 2 and led["by_reason"]["price_instinct"]["n"] == 1
    assert led["after_kickoff"]["n"] == 1 and led["after_kickoff"]["net"] == -200.0
    vt = vetoed_ledger(data, "2026-10")
    assert (vt["n"], vt["net"], vt["codes"], vt["unrecorded"]) == (1, -100.0, {"V2": 1}, 1)
    monkeypatch.setattr("nutmeg.decision.account.experiment_board", lambda _d: {})
    monkeypatch.setattr("nutmeg.decision.account.rule_v3_board", lambda _d, _m: {})
    text = render_month(month_report(data, "2026-10"))
    assert "开球后才写理由（不计入上面）：1 张" in text
    assert "审票否决仍买**：本月 1 张 投入 ¥100 净 -100（V2×1）" in text


def test_draft_board_replays_the_month_issues_without_the_stop_loss(tmp_path: Path,
                                                                    monkeypatch) -> None:
    """足彩的镜子（2026-10-06）：本月期次（按停售日归月）回放实际 / 初稿 / 空仓，不套止损。"""
    from types import SimpleNamespace

    from nutmeg.decision import account

    data = _data(tmp_path)
    (data / "zucai" / "26134-issue.json").write_text(
        json.dumps({"sale_deadline": "2026-09-28 22:00"}), encoding="utf-8")
    calls: list = []

    def fake_run_gym(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(per_policy={
            "real": {"slips": 3, "stake": 1288, "net": -1288.0, "roi": -1.0, "keys": 1},
            "zucai_draft": {"slips": 1, "stake": 324, "net": -324.0, "roi": -1.0, "keys": 1},
            "flat": {"slips": 0, "stake": 0, "net": 0.0, "roi": 0.0, "keys": 0}})

    monkeypatch.setattr("nutmeg.gym.board.list_issues", lambda _d: ["26134", "26135"])
    monkeypatch.setattr("nutmeg.gym.run.run_gym", fake_run_gym)
    board = account.draft_board(data, "2026-10")
    assert calls[0]["issues"] == ["26135"] and calls[0]["days"] == []
    assert calls[0]["stop_loss"] >= 10**9 and board["issues"] == 1
    monkeypatch.setattr("nutmeg.decision.account.experiment_board", lambda _d: {})
    monkeypatch.setattr("nutmeg.decision.account.rule_v3_board", lambda _d, _m: {})
    text = account.render_month(account.month_report(data, "2026-10"))
    assert "| 机器初稿 | 1 | 1 | 324 | -324 | -100.0% |" in text
    assert "足彩：实际出票 vs 机器初稿 vs 空仓" in text


def test_unreadable_ledger_is_reported_absent_not_zero(tmp_path: Path, monkeypatch) -> None:
    """登记簿坏了：偏离账与否决账写明缺席，而不是印「本月 0 张」（2026-10-08 检查）。"""
    data = _data(tmp_path)
    monkeypatch.setattr("nutmeg.decision.account.experiment_board", lambda _d: {})

    def boom(_data_dir):
        raise ValueError("bad line 7")

    monkeypatch.setattr("nutmeg.decision.betslip.load_slips", boom)
    text = render_month(month_report(data, "2026-10"))
    assert "两张账缺席" in text and "bad line 7" in text
    assert "本月 0 张带理由" not in text and "**审票否决仍买**：本月" not in text
