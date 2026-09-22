import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_paths import RESULTS_90, day_dir
from nutmeg.decision.day_runner import JOBS, DayContext, planned_commands, run_job
from nutmeg.decision.day_timeline import read_timeline

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=BJ)


def _runner(log: list[list[str]]):
    def run(cmd):
        log.append(list(cmd))
        if "workbench-export" in cmd:
            out = Path(cmd[cmd.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("# 复盘底稿\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "ok", "")
        if "grade-rx" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "rx error: 没有 outcome")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")
    return run


def _ctx(tmp_path: Path, log) -> DayContext:
    data = tmp_path / "data"
    (data / "jczq" / "daily" / "2026-09-23").mkdir(parents=True)
    (data / "jczq" / "daily" / "2026-09-23" / "jczq-legs-base.json").write_text(
        json.dumps({"day": "2026-09-23", "legs": {}}), encoding="utf-8")
    return DayContext(root=tmp_path, data_dir=data, date="2026-09-23",
                      runner=_runner(log), now=lambda: NOW)


def test_jobs_and_planned_settle_commands(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    assert JOBS == ("settle", "brief", "session")
    cmds = planned_commands(ctx, "settle")
    assert cmds[0][:4] == ["uv", "run", "nutmeg", "workbench-export"] and "2026-09-22" in cmds[0]
    assert not any("betslip" in c for c in cmds)  # no results-90.json yet
    (day_dir(ctx.data_dir, "2026-09-23") / RESULTS_90).parent.mkdir(parents=True, exist_ok=True)
    (day_dir(ctx.data_dir, "2026-09-23") / RESULTS_90).write_text("{}", encoding="utf-8")
    assert any("betslip" in c and "settle" in c for c in planned_commands(ctx, "settle"))
    assert planned_commands(ctx, "brief") == [] and planned_commands(ctx, "session") == []


def test_settle_runs_subprocesses_records_timeline_and_is_idempotent(tmp_path: Path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log)
    (ctx.data_dir / "zucai").mkdir()
    (ctx.data_dir / "zucai" / "26132-issue.json").write_text(
        json.dumps({"issue_id": "26132", "sale_deadline": "2026-09-23T21:00:00+08:00"}),
        encoding="utf-8")
    (ctx.data_dir / "zucai" / "26132-rx.json").write_text("{}", encoding="utf-8")
    rec = run_job(ctx, "settle")
    # one sub-command failed → job exit 1, but retro exists
    assert rec.exit == 1 and "grade-rx" in rec.summary
    assert (day_dir(ctx.data_dir, "2026-09-23") / "retro.md").exists()
    assert rec.evidence_path.endswith("retro.md")
    rows = read_timeline(ctx.data_dir, "2026-09-23")
    assert rows[-1]["job"] == "settle" and rows[-1]["commands"][0]["exit"] == 0
    calls = len(log)
    assert run_job(ctx, "settle").summary.startswith("skipped") and len(log) == calls
    assert run_job(ctx, "settle", force=True).job == "settle" and len(log) > calls


def test_brief_job_writes_brief_decisions_and_session(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    rec = run_job(ctx, "brief")
    out = day_dir(ctx.data_dir, "2026-09-23")
    assert rec.exit == 0 and (out / "brief.json").exists() and (out / "brief.md").exists()
    assert (out / "decisions.json").exists() and (out / "session.md").exists()
    assert json.loads((out / "brief.json").read_text(encoding="utf-8"))["date"] == "2026-09-23"


def test_session_job_requires_brief_first(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    rec = run_job(ctx, "session")
    assert rec.exit == 1 and "brief.json" in rec.summary
    run_job(ctx, "brief")
    assert run_job(ctx, "session").exit == 0
