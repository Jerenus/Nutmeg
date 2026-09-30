import json
import subprocess
from datetime import datetime, timedelta, timezone
from datetime import datetime as _dt
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
    assert JOBS == ("settle", "brief", "session", "results", "broadcast", "dream")
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


def test_results_job_writes_results_90_and_settle_then_picks_it_up(tmp_path: Path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log)
    (ctx.data_dir / "jczq" / "jc-results.json").write_text(
        json.dumps({"2026-09-22": {"周二001": {"match_id": "1", "ft_home": 1, "ft_away": 0}}}),
        encoding="utf-8")
    rec = run_job(ctx, "results")
    assert rec.exit == 0 and "written=1" in rec.summary
    assert any("betslip" in c for c in planned_commands(ctx, "settle"))


def test_broadcast_job_uses_injected_sender(tmp_path: Path):
    sent: list[str] = []
    ctx = _ctx(tmp_path, [])
    ctx.sender = sent.append
    ctx.now = lambda: _dt(2026, 9, 23, 19, 5, tzinfo=BJ)
    out = day_dir(ctx.data_dir, "2026-09-23")
    out.mkdir(parents=True, exist_ok=True)
    (out / "decisions.json").write_text(json.dumps([{
        "id": "read:周三001", "kind": "approve_read", "subject": "A vs B", "status": "open",
        "deadline": "2026-09-23T19:30:00+08:00", "default_action": "跟市场"}]), encoding="utf-8")
    rec = run_job(ctx, "broadcast")
    assert rec.exit == 0 and sent and "剩 25 分" in sent[0] and "sent=1" in rec.summary
    assert run_job(ctx, "broadcast").summary.endswith("sent=0 failed=0")  # deduplicated


def test_brief_job_with_logic_uses_injected_claude(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    day = ctx.data_dir / "jczq" / "daily" / "2026-09-23"
    (day / "jczq-legs-base.json").write_text(json.dumps({"day": "2026-09-23", "legs": {
        "周三001": {"match_id": "m", "name": "A vs B", "kickoff_bj": "2026-09-23T19:30:00+08:00",
                   "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}}}), encoding="utf-8")
    ctx.claude = lambda p, s: (0, json.dumps({"code": "周三001", "logic": "fair 定面。",
                                              "cites": ["market.fair", "labels.judgment_tier"]}))
    rec = run_job(ctx, "brief", with_logic=True)
    out = day_dir(ctx.data_dir, "2026-09-23")
    brief = json.loads((out / "brief.json").read_text(encoding="utf-8"))
    assert rec.exit == 0 and brief["jczq"]["matches"][0]["logic"]["status"] == "ok"
    assert "fair 定面。" in (out / "brief.md").read_text(encoding="utf-8")


def test_brief_refresh_without_logic_carries_the_previous_explanation(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    day = ctx.data_dir / "jczq" / "daily" / "2026-09-23"
    (day / "jczq-legs-base.json").write_text(json.dumps({"day": "2026-09-23", "legs": {
        "周三001": {"match_id": "m", "name": "A vs B", "kickoff_bj": "2026-09-23T19:30:00+08:00",
                   "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}}}), encoding="utf-8")
    ctx.claude = lambda p, s: (0, json.dumps({"code": "周三001", "logic": "fair 定面。",
                                              "cites": ["market.fair", "labels.judgment_tier"]}))
    assert run_job(ctx, "brief", with_logic=True).exit == 0
    out = day_dir(ctx.data_dir, "2026-09-23")
    assert run_job(ctx, "brief").exit == 0                      # 14:20-style refresh
    brief = json.loads((out / "brief.json").read_text(encoding="utf-8"))
    logic = brief["jczq"]["matches"][0]["logic"]
    assert logic["status"] == "ok" and logic["carried"] is True
    assert "fair 定面。" in (out / "brief.md").read_text(encoding="utf-8")


def test_results_job_fails_loudly_when_yesterdays_board_is_unsealed(tmp_path: Path):
    """2026-09-27 出生事故：9/26 板 25 场缺 1 场，回填不封存 → results 报 written=0 missing=0
    且退出 0，状态页一片绿，而 9/26 三张竞彩票和改判账全都没结。"""
    ctx = _ctx(tmp_path, [])
    (ctx.data_dir / "jczq" / "jc-results.json").write_text("{}", encoding="utf-8")
    board = ctx.data_dir / "jczq" / "daily" / "2026-09-22"
    board.mkdir(parents=True)
    (board / "sporttery_markets.json").write_text("{}", encoding="utf-8")
    rec = run_job(ctx, "results")
    assert rec.exit == 1 and "未封存" in rec.summary


def test_dream_job_runs_nightly_and_records_its_outcome(tmp_path: Path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log)

    def runner(cmd):
        log.append(list(cmd))
        out = json.dumps({"status": "skipped", "reason": "outside_window", "day": "2026-09-23"})
        return subprocess.CompletedProcess(cmd, 0, out + "\n", "")

    ctx.runner = runner
    rec = run_job(ctx, "dream")
    assert log[0][:5] == ["uv", "run", "nutmeg", "discovery", "nightly"]
    assert "--day" in log[0] and "2026-09-23" in log[0]
    assert "--jczq-dir" in log[0] and str(ctx.data_dir / "jczq") in log[0]
    assert rec.exit == 0 and rec.summary == "dream skipped outside_window"
    assert read_timeline(ctx.data_dir, "2026-09-23")[-1]["job"] == "dream"


def test_dream_job_failure_keeps_the_exit_code(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    ctx.runner = lambda cmd: subprocess.CompletedProcess(
        cmd, 1, json.dumps({"status": "failed", "reason": "shadow_store_missing"}) + "\n", ""
    )
    rec = run_job(ctx, "dream")
    assert rec.exit == 1 and rec.summary == "dream failed shadow_store_missing"


def test_dream_job_plans_the_nightly_subprocess_it_runs(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    assert planned_commands(ctx, "dream") == [[
        "uv", "run", "nutmeg", "discovery", "nightly", "--day", "2026-09-23",
        "--jczq-dir", str(ctx.data_dir / "jczq"),
    ]]


def test_settle_job_encodes_yesterdays_board_into_the_scoreboard(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    (ctx.out_dir / RESULTS_90).parent.mkdir(parents=True, exist_ok=True)
    (ctx.out_dir / RESULTS_90).write_text(
        json.dumps({"周一004": {"outcome_90": "0", "goals_h": 1, "goals_a": 4}}), encoding="utf-8")
    reads = ctx.data_dir / "jczq" / "daily" / "2026-09-22" / "reads.json"
    reads.parent.mkdir(parents=True, exist_ok=True)
    reads.write_text(json.dumps([{
        "note": "[周一004|土耳其-意大利|deep_research] …", "judgment_tier": "deep_research",
        "prior": {"home": 0.357, "draw": 0.270, "away": 0.373},
        "belief": {"home": 0.377, "draw": 0.280, "away": 0.343}}]), encoding="utf-8")
    rec = run_job(ctx, "settle")
    assert "复盘编码 jczq-2026-09-22：0 票" in rec.summary and "1 场" in rec.summary
    sb = json.loads((ctx.data_dir / "scoreboard.json").read_text(encoding="utf-8"))
    assert sb["balance_ledger"]["jczq-20260922"]["n_matches"] == 1
