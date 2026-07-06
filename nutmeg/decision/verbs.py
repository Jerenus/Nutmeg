"""五动词 CLI 实现(spec §3)。M0:sense 可跑(replay),余为骨架。

不动现有命令/launchd(M2 才切)。命令通过 cli/__init__ 的 @app.command 注册。
"""
from __future__ import annotations

from pathlib import Path


def run_sense(run_date: str, output_dir: Path, taken_at: str) -> str:
    from nutmeg.decision.sense import sense_from_snapshot
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = sense_from_snapshot(run_date, output_dir=output_dir,
                            taken_at=taken_at, store=store)
    return f"decision-sense {run_date}: 入库 {n} 场 Match+Snapshot"
