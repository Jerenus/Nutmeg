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
        "jczq-20261002": {"net": -7900, "stake": 8000},
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
    assert MONTHLY_STOP_LOSS_YUAN == 8000   # 2026-10-11 Jun 由 3000 改 6000；2026-10-18 改 8000
    calm = brake_state(data, date(2026, 9, 30))
    assert calm["tripped"] is False and calm["room"] == 6931.0
    assert "还有 ¥6,931 空间" in status_line(calm) and "2 条无法归月" in status_line(calm)
    tripped = brake_state(data, date(2026, 10, 5))
    assert tripped["net"] == -8100.0 and tripped["tripped"] is True
    assert status_line(tripped).startswith("⛔") and "空仓到月底" in status_line(tripped)
    # 2026-10-28：待结实购票按注金全损计（26149/26150 预审报「余 ¥766」实 ¥78 的根因）
    pend = brake_state(data, date(2026, 9, 30), pending={"n": 2, "stake": 7000.0})
    assert pend["effective_net"] == round(calm["net"] - 7000, 2) and pend["tripped"] is True
    assert "待结 2 张 ¥7,000 按全损计 → 实质" in status_line(pend)
    assert status_line(pend).startswith("⛔")


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
    assert brake_check(tmp_path, "26133", 384) is None          # 单张 ≤¥400（单票基准 800 的一半）
    assert brake_check(tmp_path, "26133", 448).startswith("⛔")  # 单张超 ¥400
    board({"26133": {"net": -816}},                            # 缺 stake/payout → 不猜
          {"brake_26135_precommit": {"caps": {"issue": "26135", "issue_yuan": 800}}})
    assert issue_brake(tmp_path, "26134") is None
    pre = issue_brake(tmp_path, "26135")
    assert pre == {"reason": "事前承诺 brake_26135_precommit", "slip_yuan": 400,
                   "issue_yuan": 800}


def test_day_cap_check_counts_all_channels_on_the_same_day():
    """日总帽 ¥2,000（宪法 §4，2026-10-12 入预审）：已买 + 这张 超帽 → ⛔；帽内 None。
    足彩单票基准 800（2026-10-12 Jun 400→800），刹车档取一半。"""
    from nutmeg.decision.bankroll import (
        BRAKE_SLIP_YUAN,
        DAILY_CAP_YUAN,
        ZUCAI_SLIP_CAP_YUAN,
        day_cap_check,
    )

    assert (DAILY_CAP_YUAN, ZUCAI_SLIP_CAP_YUAN, BRAKE_SLIP_YUAN) == (2000, 800, 400)
    assert day_cap_check("2026-10-12", 800, already_yuan=1200) is None           # 正好 2,000
    line = day_cap_check("2026-10-12T15:00:00", 288, already_yuan=1800)
    assert line.startswith("⛔日帽") and "2026-10-12" in line and "¥2,000" in line


def test_precommit_tightens_the_brake_but_never_loosens_it(tmp_path: Path):
    """期前定额（2026-11-08 Jun 批）：事前承诺与连续全灭刹车同时在 → 各取更严的一项。
    此前承诺优先，承诺 ¥800 会把刹车的 ¥400 放宽。"""
    from nutmeg.decision.bankroll import issue_brake

    wiped = {"26159": {"stake": 888, "payout": 0}, "26160": {"stake": 720, "payout": 0}}

    def board(caps):
        (tmp_path / "scoreboard.json").write_text(json.dumps(
            {"tickets": wiped, "adjudications": {"precommit-26162": {"caps": caps}}}),
            encoding="utf-8")

    board({"issue": "26162", "slip_yuan": 600, "issue_yuan": 1200})
    loose = issue_brake(tmp_path, "26162")
    assert (loose["slip_yuan"], loose["issue_yuan"]) == (400, 800)
    assert "连续两期全灭" in loose["reason"] and "事前承诺" in loose["reason"]
    board({"issue": "26162", "slip_yuan": 128, "issue_yuan": 256})
    tight = issue_brake(tmp_path, "26162")
    assert (tight["slip_yuan"], tight["issue_yuan"]) == (128, 256)


def test_write_precommit_records_caps_that_issue_brake_reads(tmp_path: Path):
    from nutmeg.decision.bankroll import brake_check, write_precommit

    (tmp_path / "scoreboard.json").write_text(json.dumps({"tickets": {}}), encoding="utf-8")
    key = write_precommit(tmp_path, "26162", slip_yuan=128, issue_yuan=256, note="期前定额",
                          now="2026-11-08T10:30:00+08:00")
    sb = json.loads((tmp_path / "scoreboard.json").read_text(encoding="utf-8"))
    assert key == "precommit-26162"
    assert sb["adjudications"][key] == {"caps": {"issue": "26162", "slip_yuan": 128,
                                                 "issue_yuan": 256},
                                        "note": "期前定额", "at": "2026-11-08T10:30:00+08:00"}
    assert brake_check(tmp_path, "26162", 128) is None
    assert brake_check(tmp_path, "26162", 256).startswith("⛔刹车：事前承诺 precommit-26162")


def test_post_win_check_blocks_raising_stakes_for_three_issues(tmp_path: Path):
    """中奖后三期不加码（2026-11-08 Jun 批）：中奖期之后三期，本期合计不高于中奖前三期均投入。"""
    from nutmeg.decision.bankroll import post_win_check

    (tmp_path / "scoreboard.json").write_text(json.dumps({"tickets": {
        "26149": {"stake": 600, "payout": 0}, "26150": {"stake": 0, "payout": 0},
        "26151": {"stake": 300, "payout": 0}, "26152": {"stake": 300, "payout": 0},
        "26153": {"stake": 400, "payout": 1471.0}}}), encoding="utf-8")
    line = post_win_check(tmp_path, "26154", 256, already_yuan=200)
    assert line.startswith("⛔中奖后不加码：26153 中奖后第 1 期")
    assert "中奖前三期均 ¥400" in line                 # 26149/26151/26152；空仓期不算
    assert post_win_check(tmp_path, "26154", 256) is None
    assert post_win_check(tmp_path, "26156", 512).startswith("⛔中奖后不加码：26153 中奖后第 3 期")
    assert post_win_check(tmp_path, "26157", 2000) is None  # 三期以后不管


def test_account_precommit_cli_writes_the_caps(tmp_path: Path):
    from typer.testing import CliRunner

    from nutmeg.interfaces.cli import app

    (tmp_path / "scoreboard.json").write_text(json.dumps({"tickets": {}}), encoding="utf-8")
    out = CliRunner().invoke(app, ["account", "precommit", "--issue", "26162", "--slip-yuan", "128",
                                   "--issue-yuan", "256", "--note", "热板定额",
                                   "--data-dir", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert "期前定额 26162：单票 ≤¥128、本期合计 ≤¥256" in out.output
    caps = json.loads((tmp_path / "scoreboard.json").read_text("utf-8"))["adjudications"]
    assert caps["precommit-26162"]["caps"] == {"issue": "26162", "slip_yuan": 128,
                                               "issue_yuan": 256}
