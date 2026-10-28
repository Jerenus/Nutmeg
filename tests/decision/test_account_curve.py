"""账房曲线（2026-10-28 第 7 阶段 Task 7.1）：按日累计、止损线换档、实质点、归月口径不变。"""
import json
from datetime import date
from pathlib import Path

from nutmeg.decision.account import daily_curve
from nutmeg.decision.bankroll import (
    MONTHLY_STOP_LOSS_YUAN,
    STOP_LOSS_HISTORY,
    month_net,
    stop_loss_on,
    ticket_day,
    ticket_month,
)

NINE = {str(i): "3" for i in range(1, 10)}


def _data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "zucai").mkdir(parents=True)
    for issue, deadline in (("26134", "2026-09-28 22:00"), ("26135", "2026-10-03 21:00"),
                            ("26140", "2026-10-12 20:00"), ("26145", "2026-10-19 21:30"),
                            ("26150", "2026-10-25 21:30"), ("26199", "10月")):
        (data / "zucai" / f"{issue}-issue.json").write_text(
            json.dumps({"issue_id": issue, "sale_deadline": deadline}), encoding="utf-8")
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "jczq-20260928": {"net": -350, "stake": 350},
        "26134": {"net": -539.0, "stake": 756},
        "jczq-20261002": {"net": -120, "stake": 200},
        "26135": {"net": 300, "stake": 100},
        "jczq-20261003": {"net": -80.5, "stake": 100},
        "jczq-20261005": {"net": 0, "stake": 0},                 # 空仓日：不出点
        "26140": {"net": -2000, "stake": 2000},
        "26145": {"net": -1500.25, "stake": 1600},
        "26133": {"net": -816, "stake": 816},                    # 无 issue.json → 不归月
        "26199": {"net": -1, "stake": 1},                        # 坏 deadline → 不归月
    }}), encoding="utf-8")
    (data / "betslips.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"slip_id": "26150-T1", "channel": "renjiu", "placed_at": "2026-10-25", "purchased": True,
         "issue": "26150", "faces": NINE, "multiplier": 32, "legs": []},       # 待结 ¥64
    ]) + "\n", encoding="utf-8")
    return data


def test_daily_curve_matches_month_net(tmp_path: Path):
    data = _data(tmp_path)
    curve = daily_curve(data, "2026-10", today=date(2026, 10, 28))
    assert [p["day"] for p in curve["points"]] == [
        "2026-10-02", "2026-10-03", "2026-10-12", "2026-10-19"]
    # 10-03 同日两条（竞彩 −80.5 + 26135 +300）合成一步
    assert [p["net"] for p in curve["points"]] == [-120.0, 99.5, -1900.5, -3400.75]
    assert curve["points"][-1]["net"] == month_net(data, "2026-10")["net"]
    assert daily_curve(data, "2026-09", today=date(2026, 10, 28))["points"][-1]["net"] == \
        month_net(data, "2026-09")["net"]


def test_stop_loss_line_steps_on_10_11_and_10_18(tmp_path: Path):
    data = _data(tmp_path)
    curve = daily_curve(data, "2026-10", today=date(2026, 10, 28))
    assert [p["line"] for p in curve["points"]] == [3000, 3000, 6000, 8000]
    assert curve["moves"] == [{"day": "2026-10-11", "from": 3000, "to": 6000},
                              {"day": "2026-10-18", "from": 6000, "to": 8000}]
    assert daily_curve(data, "2026-09", today=date(2026, 10, 28))["moves"] == []
    assert [stop_loss_on(d) for d in ("2026-09-30", "2026-10-10", "2026-10-11", "2026-10-17",
                                      "2026-10-18", "2026-11-02")] == [None, 3000, 6000, 6000,
                                                                       8000, 8000]


def test_stop_loss_history_ends_at_the_live_line():
    assert STOP_LOSS_HISTORY[-1][1] == MONTHLY_STOP_LOSS_YUAN
    assert [d for d, _ in STOP_LOSS_HISTORY] == sorted(d for d, _ in STOP_LOSS_HISTORY)


def test_effective_point_charges_pending_stake(tmp_path: Path):
    data = _data(tmp_path)
    curve = daily_curve(data, "2026-10", today=date(2026, 10, 28))
    assert curve["effective"] == {"day": "2026-10-28", "net": -3400.75 - 64}
    # 过去的月仍有待结票 → 月末；没有 → None
    assert daily_curve(data, "2026-10", today=date(2026, 11, 2))["effective"] == \
        {"day": "2026-10-31", "net": -3464.75}
    assert daily_curve(data, "2026-09", today=date(2026, 10, 28))["effective"] is None


def test_ticket_month_is_unchanged_and_derived_from_ticket_day(tmp_path: Path):
    data = _data(tmp_path)
    cases = {"jczq-20260928": "2026-09", "26134": "2026-09", "26135": "2026-10",
             "26133": None, "26199": None, "jczq-2026": None}
    assert {k: ticket_month(k, data) for k in cases} == cases
    assert ticket_day("jczq-20261002", data) == "2026-10-02"
    assert ticket_day("26140", data) == "2026-10-12"
    assert ticket_day("26133", data) is None
