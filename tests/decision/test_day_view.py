import json
from datetime import date
from pathlib import Path

from nutmeg.decision.day_paths import day_dir
from nutmeg.decision.day_view import day_view


def test_day_view_merges_everything_and_degrades(tmp_path: Path):
    data = tmp_path / "data"
    out = day_dir(data, "2026-09-23")
    out.mkdir(parents=True)
    brief = {
        "date": "2026-09-23",
        "jczq": {"matches": [], "counts": {}},
        "zucai": {"issue": None},
        "rsi": None,
        "factors": [],
        "errors": [],
    }
    (out / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    decisions = [{"id": "rsi:0", "status": "open"}]
    (out / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    timeline = [{"job": "brief", "exit": 0, "finished_at": "x", "summary": "ok"}]
    (out / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    (out / "retro.md").write_text("# 复盘底稿\n- 场1 断", encoding="utf-8")
    view = day_view(
        data_dir=data, date="2026-09-23",
        plists_dir=tmp_path / "nope", logs_dir=tmp_path / "nope",
        launchctl_text="", today=date(2026, 9, 23),
    )
    assert view["date"] == "2026-09-23" and view["brief"]["date"] == "2026-09-23"
    assert view["decisions"][0]["id"] == "rsi:0" and view["timeline"][0]["job"] == "brief"
    assert view["retro"].startswith("# 复盘底稿") and view["discussion"] == []
    assert view["launchd"] == [] and view["errors"] == []


def test_day_view_reports_missing_brief_without_failing(tmp_path: Path):
    view = day_view(
        data_dir=tmp_path, date="2026-09-23",
        plists_dir=tmp_path, logs_dir=tmp_path,
        launchctl_text="", today=date(2026, 9, 23),
    )
    assert view["brief"] is None and view["retro"] is None
    assert any("brief.json" in e for e in view["errors"])
