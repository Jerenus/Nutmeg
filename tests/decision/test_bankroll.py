import json
from datetime import date
from pathlib import Path

from nutmeg.decision.bankroll import (
    MONTHLY_STOP_LOSS_YUAN,
    brake_state,
    month_net,
    status_line,
    ticket_month,
)


def _data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "zucai").mkdir(parents=True)
    (data / "zucai" / "26134-issue.json").write_text(
        json.dumps({"issue_id": "26134", "sale_deadline": "2026-09-28 22:00"}), encoding="utf-8")
    (data / "zucai" / "26135-issue.json").write_text(
        json.dumps({"issue_id": "26135", "sale_deadline": "2026-10-03 21:00"}), encoding="utf-8")
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "jczq-20260926": {"net": -180, "stake": 180},
        "jczq-20260928": {"net": -350.0, "stake": 350},
        "26134": {"net": -539.0, "stake": 756},
        "26133": {"net": -816, "stake": 816},            # 无 issue.json → 无法归月
        "26135": {"net": -200, "stake": 200},
        "jczq-20261002": {"net": -5900, "stake": 6000},
        "26129": {"net": -1164, "stake": None},
    }}), encoding="utf-8")
    return data


def test_ticket_month_resolves_dates_and_issue_deadlines(tmp_path: Path):
    data = _data(tmp_path)
    assert ticket_month("jczq-20260928", data) == "2026-09"
    assert ticket_month("26134", data) == "2026-09"
    assert ticket_month("26135", data) == "2026-10"
    assert ticket_month("26133", data) is None


def test_month_net_sums_only_the_month_and_reports_unresolved_keys(tmp_path: Path):
    data = _data(tmp_path)
    sep = month_net(data, "2026-09")
    assert sep["net"] == -1069.0 and sep["stake"] == 1286.0
    assert sorted(k for k, _ in sep["entries"]) == ["26134", "jczq-20260926", "jczq-20260928"]
    assert sorted(sep["unknown"]) == ["26129", "26133"]


def test_brake_trips_at_the_stop_loss_and_prints_room_otherwise(tmp_path: Path):
    data = _data(tmp_path)
    assert MONTHLY_STOP_LOSS_YUAN == 6000   # 2026-10-11 Jun 由 3000 改
    calm = brake_state(data, date(2026, 9, 30))
    assert calm["tripped"] is False and calm["room"] == 4931.0
    assert "还有 ¥4,931 空间" in status_line(calm) and "2 条无法归月" in status_line(calm)
    tripped = brake_state(data, date(2026, 10, 5))
    assert tripped["net"] == -6100.0 and tripped["tripped"] is True
    assert status_line(tripped).startswith("⛔") and "空仓到月底" in status_line(tripped)


def test_issue_brake_after_two_wiped_issues_or_an_explicit_precommit(tmp_path: Path):
    """期级刹车（2026-10-06 起预审否决）：本期之前有下注的最近两期都全灭 → 帽减半；
    记分牌事前承诺（caps.issue）优先；缺数不猜。"""
    from nutmeg.decision.bankroll import brake_check, issue_brake

    def board(tickets, adjudications=None):
        (tmp_path / "scoreboard.json").write_text(json.dumps(
            {"tickets": tickets, "adjudications": adjudications or {}}), encoding="utf-8")

    board({"26131": {"stake": 310, "payout": 0, "net": -310},
           "26130": {"stake": 0, "payout": 0, "net": 0},           # 空仓期不算
           "26132": {"stake": 1362, "payout": 0, "net": -1362},
           "26134": {"stake": 756, "payout": 217.0, "net": -539.0}})
    assert issue_brake(tmp_path, "26133")["reason"] == "连续两期全灭（26131、26132）"
    assert issue_brake(tmp_path, "26135") is None              # 26134 有派奖
    assert brake_check(tmp_path, "26133", 200) is None          # 帽内
    line = brake_check(tmp_path, "26133", 192, already_yuan=700)
    assert line.startswith("⛔刹车") and "合计 ≤¥800" in line   # 同期合计超帽
    assert brake_check(tmp_path, "26133", 384).startswith("⛔")  # 单张超 ¥200
    board({"26133": {"net": -816}},                            # 缺 stake/payout → 不猜
          {"brake_26135_precommit": {"caps": {"issue": "26135", "issue_yuan": 800}}})
    assert issue_brake(tmp_path, "26134") is None
    pre = issue_brake(tmp_path, "26135")
    assert pre == {"reason": "事前承诺 brake_26135_precommit", "slip_yuan": 200,
                   "issue_yuan": 800}
