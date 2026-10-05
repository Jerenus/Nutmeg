"""并集样本池的 Read 自动进本体（Jun 2026-09-27 批准：只交未开球场次）。

- 开球后一律不交：赛后补交的判断不是前瞻样本；
- 与上次成功提交的内容相同不交：定时重建每次换 read_id 后缀，不去重会每小时灌一版；
- 提交失败不记状态，下次重试；整批成功但其中某几条被内核拒收（`decision-read` 退出码仍是 0，
  输出里列「拒绝: read_id:原因」）的，那几条也不记状态并打到 stderr（2026-10-05：26135 场11
  因价格三面和为 0.9999 被拒，却被记成已交，此后每次刷新都以为不用再交）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

Submit = Callable[[Path], tuple[int, str]]


def _digest(read: dict) -> str:
    body = {key: read.get(key) for key in ("judge", "prior", "belief", "stance")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def rejected_read_ids(output: str) -> set[str]:
    """`decision-read` 输出「… | 拒绝: rid:原因; rid:原因」→ {rid}。"""
    if "拒绝:" not in (output or ""):
        return set()
    tail = output.split("拒绝:", 1)[1].strip().splitlines()[0]
    return {part.strip().split(":", 1)[0] for part in tail.split("; ") if part.strip()}


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
    rejected = rejected_read_ids(_output)
    if rejected:
        print(f"⚠️Read 交本体被拒 {len(rejected)} 条（不记已交，下次重试）："
              f"{_output.split('拒绝:', 1)[-1].strip()[:400]}", file=sys.stderr)
    todo = [read for read in todo if read.get("read_id") not in rejected]
    state.update({read["match_id"]: _digest(read) for read in todo})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return [read["read_id"] for read in todo]
