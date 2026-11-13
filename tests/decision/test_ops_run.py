import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.ops_run import failed_segments, read_ledger, run_job
from nutmeg.decision.ops_status import format_status

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 12, 9, 45, tzinfo=BJ)


def _runner(cmd: str) -> subprocess.CompletedProcess:
    if "results" in cmd:
        return subprocess.CompletedProcess(cmd, 1, "day results: written=0\n",
                                           "⚠️源日有板但赛果未封存\n")
    return subprocess.CompletedProcess(cmd, 0, "day settle: 完成\n", "")


def test_run_job_records_every_segment_and_fails_when_any_segment_fails(tmp_path: Path):
    out: list[str] = []
    err: list[str] = []
    code = run_job(
        "day.settle", ["nutmeg day run --job results", "nutmeg day run --job settle"],
        data_dir=tmp_path, cwd=tmp_path, now=lambda: NOW, runner=_runner,
        echo=out.append, echo_err=err.append,
    )
    assert code == 1                                   # 2026-10-12：`;` 串联会把它报成 0
    assert out[-1] == "NUTMEG_FAILED day.settle step=1/2 exit=1 2026-10-12T09:45:00+08:00"
    assert "day settle: 完成" in out                   # 前段失败，后段照跑
    assert err == ["⚠️源日有板但赛果未封存"]
    rows = read_ledger(tmp_path, day="2026-10-12")
    assert [(r["step"], r["exit"]) for r in rows] == [(1, 1), (2, 0)]
    assert rows[0]["tail"] == "⚠️源日有板但赛果未封存"
    assert read_ledger(tmp_path, day="2026-10-11") == []


def test_run_job_ok_mark_carries_timestamp(tmp_path: Path):
    out: list[str] = []
    code = run_job("rsi.loop", ["nutmeg rsi loop"], data_dir=tmp_path, cwd=tmp_path,
                   now=lambda: NOW, runner=_runner, echo=out.append, echo_err=out.append)
    assert code == 0 and out[-1] == "NUTMEG_OK rsi.loop 2026-10-12T09:45:00+08:00"


def test_failed_segments_show_under_the_job_row(tmp_path: Path):
    ledger = tmp_path / "logs" / "runs.jsonl"
    ledger.parent.mkdir()
    ledger.write_text(
        json.dumps({"ts": "2026-10-12T09:45:10+08:00", "label": "day.settle", "step": 1,
                    "n": 2, "cmd": "nutmeg day run --job results", "exit": 1, "secs": 3.2,
                    "tail": "⚠️源日有板但赛果未封存"}) + "\nnot json\n",
        encoding="utf-8")
    segs = failed_segments(tmp_path, day="2026-10-12")
    assert list(segs) == ["day.settle"]
    assert segs["day.settle"][0].startswith("09:45 段 1/2 exit=1 nutmeg day run --job results — ⚠️")
    text = format_status([], [], [], today=NOW.date(), segments=segs)
    assert "launchd" in text                           # 没有 agent 行时不崩


def _auth_runner(cmd: str) -> subprocess.CompletedProcess:
    if "research" in cmd:
        return subprocess.CompletedProcess(
            cmd, 1, "", "⚠️ claude CLI 认证失败（登录过期）：本轮已停\n")
    return subprocess.CompletedProcess(cmd, 0, "ok\n", "")


def test_auth_failure_segment_calls_the_alert_once(tmp_path: Path):
    """2026-11-13：凭据被吊销，research / rsi 连挂两天，通知账里一条推送都没有。"""
    seen: list = []
    code = run_job(
        "jczq.research", ["nutmeg decision-am", "nutmeg research run", "nutmeg research refresh"],
        data_dir=tmp_path, cwd=tmp_path, now=lambda: NOW, runner=_auth_runner,
        echo=lambda _t: None, echo_err=lambda _t: None, on_auth_failure=seen.append,
    )
    assert code == 1
    assert [(r.label, r.step) for r in seen] == [("jczq.research", 2)]


def test_ordinary_failure_does_not_call_the_auth_alert(tmp_path: Path):
    seen: list = []
    run_job("day.settle", ["nutmeg day run --job results"], data_dir=tmp_path, cwd=tmp_path,
            now=lambda: NOW, runner=_runner, echo=lambda _t: None, echo_err=lambda _t: None,
            on_auth_failure=seen.append)
    assert seen == []


def test_alert_that_raises_never_changes_the_job_outcome(tmp_path: Path):
    def boom(_result):
        raise RuntimeError("telegram down")

    out: list[str] = []
    code = run_job("rsi.sweep", ["nutmeg research run"], data_dir=tmp_path, cwd=tmp_path,
                   now=lambda: NOW, runner=_auth_runner, echo=out.append,
                   echo_err=lambda _t: None, on_auth_failure=boom)
    assert code == 1 and out[-1].startswith("NUTMEG_FAILED rsi.sweep")


def test_auth_alert_text_names_the_job_and_the_fix():
    from nutmeg.decision.ops_run import SegmentResult, auth_alert

    result = SegmentResult(ts="2026-11-13T10:01:13+08:00", label="jczq.research", step=2, n=3,
                           cmd="nutmeg research run", exit=1, secs=1.0, tail="…")
    kind, key, text = auth_alert(result)
    assert (kind, key) == ("ops.claude-auth", "2026-11-13")      # 一天只推一次
    assert "jczq.research" in text and "claude setup-token" in text
