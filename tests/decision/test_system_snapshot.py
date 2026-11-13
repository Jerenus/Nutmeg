"""版图快照（版图第 2 版拓展 6）：一条只读命令给出结构数字，结构变化有据可比。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from nutmeg.decision.system_snapshot import (
    code_stats,
    inbox_stats,
    kernel_stats,
    launchd_stats,
    runs_stats,
    snapshot,
)


def test_code_stats_counts_package_lines_test_functions_and_route_decorators(tmp_path: Path):
    (tmp_path / "nutmeg" / "interfaces").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "nutmeg" / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (tmp_path / "nutmeg" / "interfaces" / "web.py").write_text(
        '@app.get("/a")\ndef a(): ...\n\n\n@app.post("/b")\ndef b(): ...\n', encoding="utf-8")
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_one(): ...\n\n\ndef test_two(): ...\n\n\ndef helper(): ...\n", encoding="utf-8")
    assert code_stats(tmp_path) == {"nutmeg_py_files": 2, "nutmeg_py_lines": 8,
                                    "test_functions": 2, "web_route_decorators": 2}


def test_kernel_stats_lists_empty_tables_without_writing(tmp_path: Path):
    db = tmp_path / "ontology.db"
    with sqlite3.connect(db) as conn:
        conn.execute("create table full (x)")
        conn.execute("create table hollow (x)")
        conn.execute("insert into full values (1)")
    before = db.stat().st_mtime_ns
    assert kernel_stats(db) == {"table_count": 2, "empty_tables": ["hollow"]}
    assert db.stat().st_mtime_ns == before


def test_launchd_stats_separates_uninstalled_and_not_loaded(tmp_path: Path):
    repo, installed = tmp_path / "repo", tmp_path / "installed"
    repo.mkdir()
    installed.mkdir()
    for name in ("a", "b", "c"):
        (repo / f"com.nutmeg.{name}.plist").write_text("", encoding="utf-8")
    for name in ("a", "b"):
        (installed / f"com.nutmeg.{name}.plist").write_text("", encoding="utf-8")
    out = launchd_stats(repo, installed, loaded={"com.nutmeg.a", "com.nutmeg.c", "com.apple.x"})
    assert out == {"defined": 3, "installed": 2, "loaded": 2,
                   "uninstalled": [{"label": "com.nutmeg.c", "loaded": True}],
                   "not_loaded": ["com.nutmeg.b"]}


def test_runs_stats_counts_ok_and_failed_segments_per_job_since_a_day(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    rows = [
        {"ts": "2026-11-05T10:00:00+08:00", "label": "rsi.loop", "exit": 1},   # 窗口之前
        {"ts": "2026-11-06T10:45:00+08:00", "label": "rsi.loop", "exit": 1},
        {"ts": "2026-11-07T10:45:00+08:00", "label": "rsi.loop", "exit": 0},
        {"ts": "2026-11-07T08:00:00+08:00", "label": "day.am", "exit": 0},
    ]
    (logs / "runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n{坏行\n", encoding="utf-8")
    assert runs_stats(tmp_path, since="2026-11-06") == {
        "since": "2026-11-06",
        "jobs": {"rsi.loop": {"ok": 1, "failed": 1}, "day.am": {"ok": 1, "failed": 0}},
    }


def test_inbox_stats_reports_backlog_age():
    rows = [{"status": "pending", "age_days": 38, "overdue": True},
            {"status": "pending", "age_days": 0, "overdue": False},
            {"status": "signed", "age_days": 50, "overdue": False}]
    assert inbox_stats(rows) == {"pending": 2, "overdue": 1, "oldest_days": 38}
    assert inbox_stats([]) == {"pending": 0, "overdue": 0, "oldest_days": 0}


def test_snapshot_keeps_going_when_a_block_fails(tmp_path: Path):
    def boom() -> dict:
        raise RuntimeError("内核读不出")

    out = snapshot({"code": lambda: {"nutmeg_py_lines": 3}, "kernel": boom},
                   captured_at="2026-11-13T20:00:00+08:00")
    assert out["captured_at"] == "2026-11-13T20:00:00+08:00"
    assert out["code"] == {"nutmeg_py_lines": 3}
    assert "内核读不出" in out["kernel"]["_error"]
