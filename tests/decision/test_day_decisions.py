import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_decisions import build_decisions, write_decisions

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=BJ)


def _brief() -> dict:
    return {
        "date": "2026-09-23",
        "jczq": {"matches": [
            {"code": "周三001", "name": "A vs B", "kickoff_bj": "2026-09-23T19:30:00+08:00",
             "read": {"read_id": "read-1", "status": "draft", "judge": "ai:jczq-analyst"}},
            {"code": "周三002", "name": "C vs D", "kickoff_bj": "2026-09-23T11:00:00+08:00",
             "read": {"read_id": "read-2", "status": "draft", "judge": "market-anchor"}},
            {"code": "周三003", "name": "E vs F", "kickoff_bj": "2026-09-23T22:00:00+08:00",
             "read": None},
        ], "counts": {}},
        "zucai": {"issue": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00",
                  "tiers": {"tiers_hash": "abc"}, "frontier": {"renjiu": {"points": []}},
                  "plan": None},
        "rsi": {"human_actions": ["因子 C11：propose_zero"], "failed_steps": ["team_strength"]},
    }


def _zucai(data: Path, deadline: str = "2026-09-23T21:00:00+08:00") -> None:
    zdir = data / "zucai"
    zdir.mkdir(parents=True, exist_ok=True)
    (zdir / "26132-issue.json").write_text(json.dumps(
        {"issue_id": "26132", "sale_deadline": deadline}), encoding="utf-8")


def _board(data: Path) -> None:
    day = data / "jczq" / "daily" / "2026-09-23"
    day.mkdir(parents=True, exist_ok=True)
    (day / "jczq-legs-base.json").write_text(json.dumps({"legs": {
        "周三001": {"kickoff_bj": "2026-09-23T19:30:00+08:00"},
        "周三003": {"kickoff_bj": "2026-09-23T22:00:00+08:00"}}}), encoding="utf-8")


def test_build_decisions_lists_register_rsi_and_failures_but_no_read_approvals(tmp_path: Path):
    _zucai(tmp_path)
    timeline = [{"job": "settle", "exit": 1, "summary": "boom"}]
    rows = build_decisions(_brief(), timeline, data_dir=tmp_path, now=NOW)
    by_id = {r["id"]: r for r in rows}
    assert not any(r["kind"] in ("approve_read", "plan_choose_commit") for r in rows)
    z = by_id["register:zucai:26132"]
    assert z["kind"] == "register_zucai" and z["status"] == "open"
    assert z["deadline"] == "2026-09-23T21:00:00+08:00"
    assert z["default_action"] == "未登记＝空仓（不买）"
    assert "register:jczq:2026-09-23" not in by_id                 # 没预审过 → 不提醒
    assert by_id["rsi:0"]["subject"] == "因子 C11：propose_zero"
    assert by_id["job:settle"]["kind"] == "failed_job"
    assert by_id["loop:team_strength"]["kind"] == "failed_step"


def test_register_decisions_close_once_a_purchased_slip_is_registered(tmp_path: Path):
    from nutmeg.decision.betslip import BetSlip, SlipLeg, register_slip

    legs = [SlipLeg(key="周三001", selections=("home",)), SlipLeg(key="周三003",
                                                                 selections=("home",))]
    from nutmeg.decision.day_decisions import live_register_decisions, log_preview

    _zucai(tmp_path)
    _board(tmp_path)
    log_preview(tmp_path, placed_at="2026-09-23", channel="jczq", issue="", keys=["周三003"],
                stake=40, vetoed=False, now=NOW)
    by_id = {r["id"]: r for r in live_register_decisions(tmp_path, "2026-09-23", now=NOW)}
    j = by_id["register:jczq:2026-09-23"]
    assert j["status"] == "open" and j["deadline"] == "2026-09-23T22:00:00+08:00"
    assert "预审过 1 次" in j["subject"]
    register_slip(tmp_path, BetSlip(slip_id="T", channel="jczq", placed_at="2026-09-23",
                                    legs=legs, combo_sizes=(2,), purchased=False))   # 试玩不算
    assert {r["id"]: r for r in live_register_decisions(tmp_path, "2026-09-23", now=NOW)}[
        "register:jczq:2026-09-23"]["status"] == "open"
    register_slip(tmp_path, BetSlip(slip_id="R", channel="renjiu", placed_at="2026-09-23",
                                    legs=[], issue="26132",
                                    faces={str(i): "3" for i in range(1, 10)}))
    register_slip(tmp_path, BetSlip(slip_id="J", channel="jczq", placed_at="2026-09-23",
                                    legs=legs, combo_sizes=(2,)))
    after = {r["id"]: r["status"] for r in live_register_decisions(tmp_path, "2026-09-23",
                                                                  now=NOW)}
    assert after == {"register:zucai:26132": "done", "register:jczq:2026-09-23": "done"}


def test_broadcast_decisions_drop_obsolete_kinds_and_add_live_ones(tmp_path: Path):
    from nutmeg.decision.day_decisions import broadcast_decisions

    _zucai(tmp_path)
    out = tmp_path / "daily" / "2026-09-23"
    out.mkdir(parents=True)
    (out / "decisions.json").write_text(json.dumps([
        {"id": "read:周三001", "kind": "approve_read", "status": "open",
         "deadline": "2026-09-23T19:30:00+08:00"},
        {"id": "plan:26132", "kind": "plan_choose_commit", "status": "open",
         "deadline": "2026-09-23T21:00:00+08:00"},
        {"id": "rsi:0", "kind": "rsi", "status": "open", "deadline": None}]), encoding="utf-8")
    ids = [d["id"] for d in broadcast_decisions(tmp_path, "2026-09-23", now=NOW)]
    assert ids == ["rsi:0", "register:zucai:26132"]


def test_write_decisions(tmp_path: Path):
    rows = build_decisions(_brief(), [], data_dir=tmp_path, now=NOW)
    path = write_decisions(tmp_path, "2026-09-23", rows)
    assert path.name == "decisions.json"
    assert json.loads(path.read_text(encoding="utf-8"))[0]["id"]


def test_failed_job_is_dropped_once_a_later_run_succeeds(tmp_path: Path):
    timeline = [{"job": "brief", "exit": 1, "summary": "boom"},
                {"job": "brief", "exit": 0, "summary": "ok"}]
    ids = {r["id"] for r in build_decisions(_brief(), timeline, data_dir=tmp_path, now=NOW)}
    assert "job:brief" not in ids


def test_log_preview_keeps_the_faces_and_the_ex_ante_p(tmp_path: Path):
    """选择账要的是票面与当时的 P——只有场次号的留痕事后还原不出审过哪几版（26136）。"""
    from nutmeg.decision.day_decisions import log_preview

    path = log_preview(tmp_path, placed_at="2026-10-09", channel="renjiu", issue="26136",
                       keys=["1", "2"], stake=4, vetoed=False, now=NOW,
                       faces={"1": "31", "2": "3"}, p=0.1034)
    row = json.loads(path.read_text("utf-8").splitlines()[-1])
    assert row["faces"] == {"1": "31", "2": "3"} and row["p"] == 0.1034


def test_rsi_inbox_items_keep_their_stable_id_age_and_default(tmp_path):
    """2026-10-19：闭环收件箱进决策页——id 不再按位置、默认动作不再一律「不动」。"""
    from nutmeg.decision.day_decisions import build_decisions

    brief = {"date": "2026-10-27", "rsi": {"human_actions": ["x"], "failed_steps": [],
             "inbox": [{"id": "RSI-1a2b3c", "key": "rubric_cap:F_suspension",
                        "text": "rubric F_suspension：上限 4pp → 0",
                        "default": "下一版 rubric 改上限",
                        "first_seen": "2026-10-20", "age_days": 7, "command": ""}]}}
    rows = [r for r in build_decisions(brief, [], data_dir=tmp_path,
                                       now=__import__("datetime").datetime(2026, 10, 27))
            if r["kind"] == "rsi"]
    assert [r["id"] for r in rows] == ["rsi:RSI-1a2b3c"]
    assert "积压 7 天" in rows[0]["subject"] and rows[0]["default_action"] == "下一版 rubric 改上限"


def test_zucai_subject_names_bridge_b1_trial_but_status_stays_open(tmp_path: Path):
    """桥后票 B1 是试玩票：主语改「已登记（试玩），未确认实购」，状态仍按未登记实票算。"""
    from nutmeg.decision.betslip import BetSlip, register_slip
    from nutmeg.decision.day_decisions import live_register_decisions

    _zucai(tmp_path)
    (tmp_path / "zucai" / "26132-draft.json").write_text(json.dumps({"candidates": [
        {"label": "初稿", "faces": {"1": "3"}, "stake_yuan": 64,
         "review": {"vetoed": True}}]}), encoding="utf-8")
    faces = {str(i): "3" for i in range(1, 10)}
    register_slip(tmp_path, BetSlip(slip_id="26132-B1", channel="renjiu", placed_at="2026-09-23",
                                    legs=[], issue="26132", faces=faces, purchased=False))
    z = {r["id"]: r for r in live_register_decisions(tmp_path, "2026-09-23", now=NOW)}[
        "register:zucai:26132"]
    assert z["subject"] == ("足彩 26132 桥后票 B1 已登记（试玩），未确认实购"
                            "；机器初稿 ¥64（审票 ⛔否决）")
    assert z["status"] == "open"
    register_slip(tmp_path, BetSlip(slip_id="26132-T1", channel="renjiu", placed_at="2026-09-23",
                                    legs=[], issue="26132", faces=faces))
    z = {r["id"]: r for r in live_register_decisions(tmp_path, "2026-09-23", now=NOW)}[
        "register:zucai:26132"]
    assert z["status"] == "done" and "B1" not in z["subject"]
