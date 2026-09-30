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


def test_build_decisions_lists_reads_plan_rsi_and_failures_with_deadlines(tmp_path: Path):
    timeline = [{"job": "settle", "exit": 1, "summary": "boom"}]
    rows = build_decisions(_brief(), timeline, data_dir=tmp_path, now=NOW)
    by_id = {r["id"]: r for r in rows}
    assert by_id["read:周三001"] == {
        "id": "read:周三001", "kind": "approve_read",
        "subject": "周三001 A vs B（ai:jczq-analyst 草稿）",
        "deadline": "2026-09-23T19:30:00+08:00", "default_action": "草稿不入库＝跟市场",
        "status": "open", "source": "reads.json", "auto_default": True,
    }
    assert by_id["read:周三002"]["status"] == "expired"
    assert "read:周三003" not in by_id
    assert by_id["plan:26132"]["kind"] == "plan_choose_commit"
    assert by_id["plan:26132"]["default_action"] == "空仓"
    assert by_id["plan:26132"]["deadline"] == "2026-09-23T21:00:00+08:00"
    assert by_id["rsi:0"]["subject"] == "因子 C11：propose_zero"
    assert by_id["rsi:0"]["deadline"] is None
    assert by_id["job:settle"]["kind"] == "failed_job"
    assert by_id["loop:team_strength"]["kind"] == "failed_step"


def test_approved_read_is_marked_done(tmp_path: Path):
    log = tmp_path / "jczq" / "daily" / "2026-09-23" / "decisions.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        json.dumps({"action": "approve_read", "obj_id": "read-1", "result": "read-1 入库"}) + "\n",
        encoding="utf-8",
    )
    rows = build_decisions(_brief(), [], data_dir=tmp_path, now=NOW)
    assert {r["id"]: r["status"] for r in rows}["read:周三001"] == "done"


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
