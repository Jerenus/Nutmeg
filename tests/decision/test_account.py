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
                          "slips": [{"id": "D2", "stake": 50, "payout": 150.0}]}}}),
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
