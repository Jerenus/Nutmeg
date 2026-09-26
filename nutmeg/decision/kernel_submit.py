"""并集样本池的 Read 自动进本体（Jun 2026-09-27 批准：只交未开球场次）。

- 开球后一律不交：赛后补交的判断不是前瞻样本；
- 与上次成功提交的内容相同不交：定时重建每次换 read_id 后缀，不去重会每小时灌一版；
- 提交失败不记状态，下次重试。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

Submit = Callable[[Path], tuple[int, str]]


def _digest(read: dict) -> str:
    body = {key: read.get(key) for key in ("judge", "prior", "belief", "stance")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def submit_unstarted(reads: list[dict], *, kickoffs: dict[str, str], state_path: Path,
                     now: str, submit: Submit) -> list[str]:
    """返回本次提交的 read_id；`kickoffs` = {match_id: ISO 开球}，缺开球的不交。"""
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    current = datetime.fromisoformat(now)
    todo = [
        read for read in reads
        if read.get("match_id") in kickoffs
        and datetime.fromisoformat(kickoffs[read["match_id"]]) > current
        and state.get(read["match_id"]) != _digest(read)
    ]
    if not todo:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reads.json"
        path.write_text(json.dumps(todo, ensure_ascii=False), encoding="utf-8")
        code, _output = submit(path)
    if code != 0:
        return []
    state.update({read["match_id"]: _digest(read) for read in todo})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return [read["read_id"] for read in todo]
