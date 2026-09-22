"""`/api/day/<date>` 的合成：七份输入各自 try，缺一块不塌整页（设计 §7 与观察台同规）。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from nutmeg.decision.day_ops import launchd_rows
from nutmeg.decision.day_paths import BRIEF, DECISIONS, RETRO, TIMELINE, day_dir
from nutmeg.decision.day_session import read_discussion


def _json(path: Path, errors: list[str], default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"缺 {path.name}")
    except ValueError as exc:
        errors.append(f"{path.name} 坏: {exc}")
    return default


def day_view(*, data_dir: Path, date: str, plists_dir: Path, logs_dir: Path,
             launchctl_text: str, today: date) -> dict:
    errors: list[str] = []
    out = day_dir(data_dir, date)
    brief = _json(out / BRIEF, errors, None)
    decisions = _json(out / DECISIONS, errors, [])
    timeline = _json(out / TIMELINE, errors, [])
    retro = None
    try:
        retro = (out / RETRO).read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"缺 {RETRO}")
    try:
        discussion = read_discussion(data_dir, date)
    except ValueError as exc:
        discussion = []
        errors.append(f"discussion.jsonl 坏: {exc}")
    try:
        launchd = launchd_rows(plists_dir=plists_dir, logs_dir=logs_dir,
                                launchctl_text=launchctl_text, today=today)
    except Exception as exc:  # noqa: BLE001
        launchd = []
        errors.append(f"launchd 行失败: {exc}")
    return {"date": date, "brief": brief, "decisions": decisions, "timeline": timeline,
            "retro": retro, "discussion": discussion, "launchd": launchd, "errors": errors}
