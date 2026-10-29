import json
import plistlib
import sqlite3
from datetime import datetime
from pathlib import Path

from nutmeg.decision.day_runs import day_runs, planned_times

DAY = "2026-09-24"


def _plist(folder: Path, label: str, schedule: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    doc = {"Label": label, "ProgramArguments": ["/bin/true"], **schedule}
    (folder / f"{label}.plist").write_bytes(plistlib.dumps(doc))


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def _timeline(data: Path, rows: list[dict]) -> None:
    _write(data / "daily" / DAY / "timeline.json", rows)


def _row(job: str, planned: str, finished: str, code: int = 0, summary: str = "ok") -> dict:
    return {"job": job, "planned_at": f"{DAY}T{planned}:00+08:00",
            "started_at": f"{DAY}T{finished}:00+08:00",
            "finished_at": f"{DAY}T{finished}:30+08:00", "exit": code, "summary": summary}


def _job(view: dict, job_id: str) -> dict:
    return next(j for j in view["jobs"] if j["id"] == job_id)


def test_planned_times_reads_every_launchd_schedule_shape():
    assert planned_times({"StartCalendarInterval": {"Hour": 9, "Minute": 45}}) == (
        ["09:45"], "09:45")
    times, text = planned_times({"StartCalendarInterval": [
        {"Hour": 18, "Minute": 35}, {"Hour": 12, "Minute": 0}]})
    assert times == ["12:00", "18:35"] and text == "12:00、18:35"
    hourly, text = planned_times({"StartCalendarInterval": {"Minute": 0}})
    assert len(hourly) == 24 and text == "每小时（00:00–23:00）"
    every, text = planned_times({"StartInterval": 600})
    assert len(every) == 144 and every[1] == "00:10" and text.startswith("每 10 分")


def test_timed_job_matches_runs_to_slots_and_marks_the_rest(tmp_path: Path):
    plists, data = tmp_path / "plists", tmp_path / "data"
    _plist(plists, "com.nutmeg.day.brief", {"StartCalendarInterval": [
        {"Hour": 12, "Minute": 0}, {"Hour": 14, "Minute": 20}, {"Hour": 18, "Minute": 35}]})
    _timeline(data, [
        _row("brief", "12:00", "12:07", summary="brief 8 场"),
        _row("brief", "12:59", "12:59"),                      # 手动补跑
        _row("brief", "14:20", "14:21", code=1, summary="brief 异常"),
    ])

    view = day_runs(data_dir=data, plists_dir=plists, day=DAY,
                    now=datetime(2026, 9, 24, 16, 0))

    slots = _job(view, "day.brief")["slots"]
    assert [(s["planned"], s["status"], s["at"]) for s in slots] == [
        ("12:00", "ok", "12:07"), ("14:20", "fail", "14:21"),
        ("18:35", "upcoming", None), (None, "ok", "12:59")]
    assert slots[-1]["extra"] is True
    assert view["counts"]["fail"] == 1 and view["counts"]["upcoming"] == 1
    assert view["is_today"] and view["now"] == "16:00"


def test_a_past_slot_without_evidence_is_missing(tmp_path: Path):
    plists, data = tmp_path / "plists", tmp_path / "data"
    _plist(plists, "com.nutmeg.day.settle", {"StartCalendarInterval": {"Hour": 9, "Minute": 45}})

    view = day_runs(data_dir=data, plists_dir=plists, day=DAY,
                    now=datetime(2026, 9, 25, 10, 0))

    assert _job(view, "day.settle")["slots"][0]["status"] == "missing"
    assert view["now"] is None


def test_rolling_log_job_is_unknown_on_a_past_day_not_missing(tmp_path: Path):
    plists, data = tmp_path / "plists", tmp_path / "data"
    _plist(plists, "com.nutmeg.jczq.results-backfill",
           {"StartCalendarInterval": {"Hour": 9, "Minute": 30}})

    view = day_runs(data_dir=data, plists_dir=plists, day="2026-09-20",
                    now=datetime(2026, 9, 24, 10, 0))

    assert _job(view, "jczq.results-backfill")["slots"][0]["status"] == "unknown"


def test_zucai_prep_reads_the_slot_file_or_the_no_issue_line(tmp_path: Path):
    plists, data = tmp_path / "plists", tmp_path / "data"
    _plist(plists, "com.nutmeg.zucai.prep", {"StartCalendarInterval": {"Hour": 14, "Minute": 0}})
    _plist(plists, "com.nutmeg.zucai.prep-morning",
           {"StartCalendarInterval": {"Hour": 11, "Minute": 0}})
    _write(data / "zucai" / "26132-prep-afternoon.json", {
        "issue": "26132", "run_date": DAY, "captured_at": f"{DAY}T14:00:05",
        "n_matches": 14, "intl_status": "available",
        "alignment": {"unmatched": [{"match_no": 2}], "ambiguous": []}})
    _write(data / "logs" / "zucai.prep-morning.out.log",
           f"🌙 足彩备料 {DAY}:今日无期。下一期 26133 截止 2026-09-26 21:00(2 天后)\n")

    view = day_runs(data_dir=data, plists_dir=plists, day=DAY,
                    now=datetime(2026, 9, 24, 20, 0))

    afternoon = _job(view, "zucai.prep")["slots"][0]
    assert (afternoon["status"], afternoon["at"]) == ("warn", "14:00")
    assert afternoon["summary"] == "26132 期 14 场，体彩未对齐 1 场"
    morning = _job(view, "zucai.prep-morning")["slots"][0]
    assert morning["status"] == "skip" and morning["summary"].startswith("今天没有足彩期")


def test_frequent_jobs_count_runs_against_the_slots_already_due(tmp_path: Path):
    plists, data = tmp_path / "plists", tmp_path / "data"
    _plist(plists, "com.nutmeg.rsi.sweep", {"StartCalendarInterval": {"Minute": 0}})
    _write(data / "logs" / "rsi.sweep.out.log",
           f"{DAY} sweep: ran=0 failed=0\n{DAY} sweep: ran=1 failed=2\n")

    view = day_runs(data_dir=data, plists_dir=plists, day=DAY,
                    now=datetime(2026, 9, 24, 8, 20))

    sweep = _job(view, "rsi.sweep")
    assert sweep["kind"] == "frequent" and sweep["window"] == ["07:00", "23:00"]
    assert (sweep["run_count"], sweep["due"], sweep["status"]) == (2, 2, "warn")


def test_outputs_markers_and_rsi_duties(tmp_path: Path):
    plists, data = tmp_path / "plists", tmp_path / "data"
    plists.mkdir()
    _write(data / "daily" / DAY / "brief.json", {
        "jczq": {"matches": [
            {"code": "周四001", "name": "日本-乌拉圭", "kickoff_bj": f"{DAY}T18:05:00+08:00",
             "read": {"judgment_tier": "deep_research", "confidence": 2, "moved_pp": 0.0}},
            {"code": "周四008", "name": "挪威-丹麦", "kickoff_bj": "2026-09-25T02:45:00+08:00",
             "read": {"judgment_tier": "price_only", "moved_pp": 3.0}},
        ]},
        "zucai": {"issue": "26132", "sale_deadline": f"{DAY} 19:05", "plan": None},
        "rsi": {"human_actions": [{"text": "因子 x 建议 0pp"}]},
    })
    _write(data / "daily" / DAY / "broadcasts.jsonl",
           json.dumps({"key": "read:周四001@T30", "at": f"{DAY}T17:40:41+08:00",
                       "minutes_left": 24}) + "\n")
    db = data / "ontology" / "ontology.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE rsi_duty_instances (duty_id TEXT, day TEXT, match_id TEXT, "
                     "due_at TEXT, issue TEXT, fulfilled_at TEXT)")
        conn.executemany("INSERT INTO rsi_duty_instances VALUES (?,?,?,?,?,?)", [
            ("F4:capital-plan", DAY, "", f"{DAY}T18:05:00+08:00", None, None),
            ("F5:price-band-observation", DAY, "m1", f"{DAY}T19:00:00+08:00", None, "x"),
            ("F5:price-band-observation", DAY, "m2", f"{DAY}T20:00:00+08:00", None, None),
        ])

    view = day_runs(data_dir=data, plists_dir=plists, day=DAY,
                    now=datetime.fromisoformat(f"{DAY}T19:30:00+08:00"))

    assert view["markers"] == [
        {"at": "18:05", "kind": "kickoff", "label": "周四001 日本-乌拉圭"},
        {"at": "19:05", "kind": "deadline", "label": "足彩 26132 截止"}]
    out = view["outputs"]
    assert (out["jczq"]["matches"], out["jczq"]["deep"], out["jczq"]["moved"]) == (2, 1, 1)
    assert out["zucai"] == {"issue": "26132", "deadline": f"{DAY} 19:05"}
    assert out["rsi"]["pending"] == ["因子 x 建议 0pp"]
    assert out["rsi"]["duties"] == [
        {"duty": "F4:capital-plan", "total": 1, "done": 0, "expired": 1},
        {"duty": "F5:price-band-observation", "total": 2, "done": 1, "expired": 0}]
    assert out["broadcasts"] == [{"at": "17:40", "key": "read:周四001@T30", "minutes_left": 24}]
    assert view["days"] == [DAY]


def test_an_unregistered_plist_is_reported_not_dropped_silently(tmp_path: Path):
    plists = tmp_path / "plists"
    _plist(plists, "com.nutmeg.new.thing", {"StartCalendarInterval": {"Hour": 1, "Minute": 0}})

    view = day_runs(data_dir=tmp_path, plists_dir=plists, day=DAY,
                    now=datetime(2026, 9, 24, 12, 0))

    assert view["jobs"] == []
    assert view["errors"] == ["com.nutmeg.new.thing 没有登记证据来源，页面上看不到它"]


def test_days_before_a_job_went_live_are_inactive_not_missing(tmp_path: Path):
    plists, data = tmp_path / "plists", tmp_path / "data"
    _plist(plists, "com.nutmeg.day.settle", {"StartCalendarInterval": {"Hour": 9, "Minute": 45}})
    _write(data / "daily" / "2026-09-22" / "timeline.json", [])     # 日作业从 09-22 起才有

    before = day_runs(data_dir=data, plists_dir=plists, day="2026-09-20",
                      now=datetime(2026, 9, 24, 12, 0))
    after = day_runs(data_dir=data, plists_dir=plists, day="2026-09-23",
                     now=datetime(2026, 9, 24, 12, 0))

    assert _job(before, "day.settle")["slots"][0]["status"] == "inactive"
    assert _job(after, "day.settle")["slots"][0]["status"] == "missing"


def test_monthly_job_is_planned_only_on_its_day_and_reads_the_report_as_evidence(tmp_path):
    import os
    from datetime import datetime as _dt

    from nutmeg.decision.day_runs import _account_runs, planned_times

    doc = {"StartCalendarInterval": {"Day": 1, "Hour": 16, "Minute": 10}}
    assert planned_times(doc, "2026-11-01") == (["16:10"], "每月 1 日 16:10")
    assert planned_times(doc, "2026-11-02") == ([], "每月 1 日 16:10")
    weekly = {"StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 0}}
    assert planned_times(weekly, "2026-10-05")[0] == ["09:00"]        # 2026-10-05 是周一
    assert planned_times(weekly, "2026-10-06")[0] == []
    assert planned_times({"StartCalendarInterval": {"Hour": 10, "Minute": 45}}, "2026-11-02")[0] \
        == ["10:45"]
    report = tmp_path / "analytics" / "account" / "2026-10.md"
    report.parent.mkdir(parents=True)
    report.write_text("# 账房 · 2026-10\n\n**净值 vs 空仓**：+180\n", encoding="utf-8")
    stamp = _dt(2026, 11, 1, 16, 11).timestamp()
    os.utime(report, (stamp, stamp))
    [run] = _account_runs(tmp_path, "2026-11-01")
    assert run.at == "16:11" and run.summary.startswith("**净值 vs 空仓**：+180")
    assert _account_runs(tmp_path, "2026-11-02") == []


def test_ops_run_wrapped_jobs_read_rounds_from_the_segment_ledger(tmp_path: Path):
    plists, data = tmp_path / "plists", tmp_path / "data"
    _plist(plists, "com.nutmeg.jczq.research-pm", {"StartCalendarInterval": [
        {"Hour": 16, "Minute": 30}, {"Hour": 20, "Minute": 0}]})
    day = "2026-10-27"
    seg = lambda hm, step, code, tail, label="jczq.research-pm": {  # noqa: E731
        "ts": f"{day}T{hm}:05+08:00", "label": label, "step": step, "n": 2,
        "cmd": "x", "exit": code, "secs": 1.0, "tail": tail}
    _write(data / "logs" / "runs.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in [
        seg("16:30", 1, 0, "run 9 场"), seg("16:52", 2, 0, "refresh 读 9 条"),
        seg("17:10", 1, 0, "别的作业", label="zucai.lineups"),
        seg("18:00", 1, 0, "补跑"), seg("18:20", 2, 1, "refresh 崩了"),
    ]) + "\n")

    view = day_runs(data_dir=data, plists_dir=plists, day=day,
                    now=datetime(2026, 10, 27, 19, 0))

    job = _job(view, "jczq.research-pm")
    assert view["errors"] == []
    assert [(s["planned"], s["status"], s["at"], s["summary"]) for s in job["slots"]] == [
        ("16:30", "ok", "16:30", "refresh 读 9 条"), ("20:00", "upcoming", None, ""),
        (None, "fail", "18:00", "refresh 崩了")]
