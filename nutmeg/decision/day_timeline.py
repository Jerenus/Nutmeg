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


def append_job(data_dir: Path | str, date: str, record: JobRecord) -> Path:
    path = day_dir(data_dir, date) / TIMELINE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = read_timeline(data_dir, date)
    rows.append(record.to_dict())
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def latest(rows: list[dict], job: str) -> dict | None:
    hits = [r for r in rows if r.get("job") == job]
    return hits[-1] if hits else None
