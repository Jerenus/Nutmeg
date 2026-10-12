"""`timeline.json`：每个作业一行，只追加；每行必须带时间证据（沿用 ops_status 的纪律）。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nutmeg.decision.day_paths import TIMELINE, day_dir


@dataclass
class JobRecord:
    job: str
    planned_at: str
    started_at: str
    finished_at: str
    exit: int
    summary: str
    evidence_path: str | None = None
    commands: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def read_timeline(data_dir: Path | str, date: str) -> list[dict]:
    path = day_dir(data_dir, date) / TIMELINE
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return rows if isinstance(rows, list) else []


IDLE_BROADCAST = "broadcast sent=0 failed=0"
"""每 10 分钟一次、什么都没发的播报行。"""


def _idle_broadcast(row: dict) -> bool:
    return row.get("job") == "broadcast" and row.get("exit") == 0 \
        and str(row.get("summary", "")).startswith(IDLE_BROADCAST)


def append_job(data_dir: Path | str, date: str, record: JobRecord) -> Path:
    """只追加；唯一例外：连续的「空播报」只保留最新一行（2026-10-13 降噪，
    此前一天 140 行时间线里 133 行是 `sent=0`）。发过、失败过的播报行照旧保留。"""
    path = day_dir(data_dir, date) / TIMELINE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = read_timeline(data_dir, date)
    new = record.to_dict()
    if rows and _idle_broadcast(new) and _idle_broadcast(rows[-1]):
        rows[-1] = new
    else:
        rows.append(new)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


