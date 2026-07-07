"""DecisionStore — 本体对象的唯一持久层(append-only JSONL,幂等 upsert-by-id)。

演进 judge_ledger 的整批替换幂等纪律(load→剔除同键→重写)。每类型一个文件。
不懂业务:只认对象有 .id / .to_dict / .from_dict。规模 1 万+ 再议 SQLite。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAMES = {
    "Match": "matches.jsonl",
    "MarketSnapshot": "snapshots.jsonl",
    "Read": "reads.jsonl",
    "Factor": "factors.jsonl",
    "Ticket": "tickets.jsonl",
    "Settlement": "settlements.jsonl",
    "FactorVerdict": "verdicts.jsonl",
    "Team": "teams.jsonl",
    "League": "leagues.jsonl",
}


class DecisionStore:
    def __init__(self, base_dir) -> None:
        self.base = Path(base_dir)

    def _path(self, cls) -> Path:
        return self.base / _FILENAMES[cls.__name__]

    def load(self, cls) -> list:
        path = self._path(cls)
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(cls.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, KeyError):
                logger.warning("decision store 损坏行已跳过: %r", line[:80])
        return out

    def get(self, cls, obj_id: str):
        for obj in self.load(cls):
            if obj.id == obj_id:
                return obj
        return None

    def upsert(self, obj) -> None:
        cls = type(obj)
        kept = [o for o in self.load(cls) if o.id != obj.id]
        kept.append(obj)
        path = self._path(cls)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for o in kept:
                fh.write(json.dumps(o.to_dict(), ensure_ascii=False) + "\n")

    def upsert_many(self, objs) -> None:
        for obj in objs:
            self.upsert(obj)

    def remove(self, cls, obj_id: str) -> bool:
        """按 id 删一条。删了返回 True,不存在返回 False。"""
        objs = self.load(cls)
        kept = [o for o in objs if o.id != obj_id]
        if len(kept) == len(objs):
            return False
        path = self._path(cls)
        with path.open("w", encoding="utf-8") as fh:
            for o in kept:
                fh.write(json.dumps(o.to_dict(), ensure_ascii=False) + "\n")
        return True

    # --- 血缘查询(spec §2) ---
    def reads_for_factor(self, factor_id: str) -> list:
        from nutmeg.decision.ontology import Read
        return [
            r for r in self.load(Read)
            if any(f.get("factor_id") == factor_id for f in r.factors)
        ]

    def settlement_for(self, ref_type: str, ref_id: str):
        from nutmeg.decision.ontology import Settlement
        for s in self.load(Settlement):
            if s.ref_type == ref_type and s.ref_id == ref_id:
                return s
        return None
