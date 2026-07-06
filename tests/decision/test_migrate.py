from nutmeg.decision.migrate import migrate_ledger_entries
from nutmeg.decision.ontology import Read, Settlement
from nutmeg.decision.store import DecisionStore


def _ledger():
    return [
        {"date": "2026-06-27", "kind": "pick", "match_id": "M02", "fixture": "阿 vs 奥",
         "judgment": "draw", "confidence": 4, "pending": False,
         "judgment_hit": True, "score_hit": False},
        {"date": "2026-06-27", "kind": "pick", "match_id": "M03", "fixture": "X vs Y",
         "judgment": "home", "confidence": 3, "pending": True},   # pending → 跳过 settlement
        {"date": "2026-06-27", "kind": "absent"},                 # 忽略
    ]


def test_migrate_creates_reads_and_settlements(tmp_path):
    store = DecisionStore(tmp_path)
    n = migrate_ledger_entries(_ledger(), store=store, source_tag="legacy-judge")
    assert n == 2                                # 返回迁移的 pick 数
    reads = store.load(Read)
    assert len(reads) == 2                       # 两个 pick(absent 忽略)
    # 已结的入 Settlement(hit),pending 的不入
    setts = store.load(Settlement)
    assert len(setts) == 1 and setts[0].hit is True
    assert setts[0].clv_pp is None               # 历史无收盘→CLV null
