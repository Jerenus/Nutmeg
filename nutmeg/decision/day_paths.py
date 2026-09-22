"""`daily/<日>/` 对象：路径与文件名常量（设计 §4）。只此一处定义，其它模块 import。"""
from __future__ import annotations

from pathlib import Path

TIMELINE = "timeline.json"
BRIEF = "brief.json"
BRIEF_MD = "brief.md"
RETRO = "retro.md"
DECISIONS = "decisions.json"
SESSION = "session.md"
DISCUSSION = "discussion.jsonl"
BROADCASTS = "broadcasts.jsonl"
RESULTS_90 = "results-90.json"


def day_dir(data_dir: Path | str, date: str) -> Path:
    return Path(data_dir) / "daily" / date


def jczq_day_dir(data_dir: Path | str, date: str) -> Path:
    return Path(data_dir) / "jczq" / "daily" / date


def zucai_dir(data_dir: Path | str) -> Path:
    return Path(data_dir) / "zucai"
