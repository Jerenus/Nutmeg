import json
from pathlib import Path

from nutmeg.decision.day_paths import TIMELINE, day_dir
from nutmeg.decision.day_timeline import JobRecord, append_job


def _rec(job: str, exit_code: int = 0) -> JobRecord:
    return JobRecord(
        job=job, planned_at="2026-09-23T07:30:00+08:00",
        started_at="2026-09-23T07:30:02+08:00", finished_at="2026-09-23T07:30:20+08:00",
        exit=exit_code, summary=f"{job} done", evidence_path=None, commands=[],
    )


def test_append_job_creates_day_dir_and_appends_in_order(tmp_path: Path):
    path = append_job(tmp_path, "2026-09-23", _rec("settle"))
    append_job(tmp_path, "2026-09-23", _rec("brief", 1))
    assert path == day_dir(tmp_path, "2026-09-23") / TIMELINE
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert [r["job"] for r in rows] == ["settle", "brief"]
    assert rows[1]["exit"] == 1


