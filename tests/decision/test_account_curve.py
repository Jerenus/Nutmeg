"""账房曲线（2026-10-28 第 7 阶段 Task 7.1）：按日累计、止损线换档、实质点、归月口径不变。"""
import json
from datetime import date
from pathlib import Path

from nutmeg.decision.account import daily_curve, draft_board, draft_curve
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


# ---- Task 7.3：足彩换成机器初稿的反事实线 ----
def _pt(day: str, net: float) -> dict:
    return {"day": day, "net": net, "line": 3000}


def test_draft_curve_skips_pending_issues():
    points = [_pt("2026-10-03", -100.0)]
    assert draft_curve(points, [{"issue": "26135", "day": "2026-10-03", "real": -100.0,
                                 "draft": None}]) == [{"day": "2026-10-03", "net": -100.0}]
    assert draft_curve(points, [{"issue": "26135", "day": "2026-10-03", "real": None,
                                 "draft": -50.0}]) == [{"day": "2026-10-03", "net": -100.0}]


def test_draft_curve_counts_issue_jun_skipped_as_real_zero():
    """Jun 那期没买（real 0.0）而初稿出了票：差额照计，期日单独出点。"""
    curve = draft_curve([_pt("2026-10-02", -120.0)],
                        [{"issue": "26136", "day": "2026-10-05", "real": 0.0, "draft": -324.0}])
    assert curve == [{"day": "2026-10-02", "net": -120.0}, {"day": "2026-10-05", "net": -444.0}]


def test_draft_curve_jczq_only_day_carries_actual_plus_prior_deltas():
    points = [_pt("2026-10-03", 300.0), _pt("2026-10-07", 250.0)]     # 10-07 只有竞彩 −50
    curve = draft_curve(points, [{"issue": "26135", "day": "2026-10-03", "real": 300.0,
                                  "draft": -100.0}])
    assert curve == [{"day": "2026-10-03", "net": -100.0}, {"day": "2026-10-07", "net": -150.0}]


def test_draft_curve_without_issues_is_the_actual_curve():
    points = [_pt("2026-10-02", -120.0), _pt("2026-10-03", 99.5)]
    assert draft_curve(points, []) == [{"day": p["day"], "net": p["net"]} for p in points]


def test_draft_board_by_issue_and_curve(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    data = _data(tmp_path)
    ledger = [
        {"issue": "26135", "key": "2026-10-03", "policy": "real", "net": 300.0},
        {"issue": "26135", "key": "2026-10-03", "policy": "zucai_draft", "net": -100.0},
        {"issue": "26135", "key": "2026-10-03", "policy": "flat", "net": 0.0},
        {"issue": "26140", "key": "2026-10-12", "policy": "real", "net": -1000.0},
        {"issue": "26140", "key": "2026-10-12", "policy": "real", "net": -1000.0},
        # 26140 初稿无行＝空仓 → 0.0；26145 初稿待结、26150 实际待结 → 不进差额
        {"issue": "26145", "key": "2026-10-19", "policy": "real", "net": -1500.25},
        {"issue": "26145", "key": "2026-10-19", "policy": "zucai_draft", "net": None},
        {"issue": "26150", "key": "2026-10-25", "policy": "real", "net": None},
        {"issue": "26150", "key": "2026-10-25", "policy": "zucai_draft", "net": -200.0},
    ]
    monkeypatch.setattr("nutmeg.gym.board.list_issues",
                        lambda _d: ["26134", "26135", "26140", "26145", "26150"])
    monkeypatch.setattr("nutmeg.gym.run.run_gym",
                        lambda **_k: SimpleNamespace(ledger=ledger, per_policy={}))
    board = draft_board(data, "2026-10")
    assert board["by_issue"] == [
        {"issue": "26135", "day": "2026-10-03", "real": 300.0, "draft": -100.0},
        {"issue": "26140", "day": "2026-10-12", "real": -2000.0, "draft": 0.0},
        {"issue": "26145", "day": "2026-10-19", "real": -1500.25, "draft": None},
        {"issue": "26150", "day": "2026-10-25", "real": None, "draft": -200.0},
    ]
    # 实际 −120 / 99.5 / −1900.5 / −3400.75；差额 10-03 −400、10-12 +2000
    assert board["curve"] == [
        {"day": "2026-10-02", "net": -120.0}, {"day": "2026-10-03", "net": -300.5},
        {"day": "2026-10-12", "net": -300.5}, {"day": "2026-10-19", "net": -1800.75},
        {"day": "2026-10-25", "net": -1800.75}]


def test_draft_board_error_has_no_curve(tmp_path: Path, monkeypatch):
    def boom(**_k):
        raise RuntimeError("gym down")

    monkeypatch.setattr("nutmeg.gym.board.list_issues", lambda _d: [])
    monkeypatch.setattr("nutmeg.gym.run.run_gym", boom)
    board = draft_board(_data(tmp_path), "2026-10")
    assert "_error" in board and "curve" not in board
