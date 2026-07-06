"""历史 judge-ledger.jsonl → Read/Settlement 一次性迁移(spec §8/§12 #3)。

历史 pick 无欧赔先验/收盘快照:只迁方向判定与命中,供因子历史与方向命中率;
brier_delta/clv 标 null(绝不伪造)。pending/absent 条目不产 Settlement。
"""
from __future__ import annotations

from nutmeg.decision.ontology import Read, Settlement

_DIRS = ("home", "draw", "away")


def migrate_ledger_entries(entries: list[dict], *, store, source_tag: str) -> int:
    """迁移 pick 条目 → Read(+已结的 Settlement)。返回迁移的 pick 数。"""
    n = 0
    for e in entries:
        if e.get("kind") != "pick":
            continue
        judgment = e.get("judgment")
        if judgment not in _DIRS:
            continue
        date = e.get("date", "")
        mid = f"M-legacy-{date}-{e.get('match_id', '')}"
        belief = {d: (1.0 if d == judgment else 0.0) for d in _DIRS}
        rid = f"R-legacy-{date}-{e.get('match_id', '')}"
        store.upsert(Read(
            read_id=rid, match_id=mid, snapshot_id="", made_at=date,
            judge=source_tag, market="had", prior={}, belief=belief,
            factors=[], confidence=int(e.get("confidence", 3) or 3),
            shadow=False, note=f"legacy migrate: {e.get('fixture', '')}",
        ))
        n += 1
        if not e.get("pending") and e.get("judgment_hit") is not None:
            store.upsert(Settlement(
                settlement_id=f"SET-read-{rid}", ref_type="read", ref_id=rid,
                settled_at=date, hit=bool(e.get("judgment_hit")),
                brier=None, clv_pp=None,       # 历史无 prior/收盘 → 双轴 null
            ))
    return n
