"""ttg 轴 Read(2026-07-07 用户定:进球轴判断也要进 Brier/CLV 双轴检验,shadow 起步攒样本)。

- settle_read 按 read.market 取 Brier 靶:had→outcome_90;ttg→total_{min(总进球,7)}。
- backfill 对带 ttg fair 的场,在 had shadow 之外再补一条 ttg shadow。
- ingest 的"真判读顶掉 shadow"守卫按 (match_id, market) 去重,had 判读不误删 ttg shadow。
"""
from nutmeg.decision.ontology import Factor, MarketSnapshot, Read
from nutmeg.decision.read_ingest import backfill_shadows, ingest_reads
from nutmeg.decision.reconcile import read_actual, settle_reads_for_matches
from nutmeg.decision.store import DecisionStore

_MID = "M-2026-07-08-测试主-测试客"

_TTG_FAIR = {f"total_{k}": p for k, p in
             enumerate((0.07, 0.18, 0.24, 0.22, 0.14, 0.08, 0.04, 0.03))}


def _sporttery_snap():
    return MarketSnapshot(
        snapshot_id="S-spot", match_id=_MID, taken_at="t",
        kind="read_time", source="sporttery",
        fair={"had": {"home": 0.45, "draw": 0.28, "away": 0.27}, "ttg": dict(_TTG_FAIR)})


def test_read_actual_per_market():
    assert read_actual("had", "home", "2:0") == "home"
    assert read_actual("ttg", "home", "2:1") == "total_3"
    assert read_actual("ttg", "away", "5:4") == "total_7"     # 7+ 封顶桶
    assert read_actual("ttg", "home", None) is None            # 缺比分→不可判
    assert read_actual("crs", "home", "2:0") is None           # 未支持市场→不产伪 Brier


def test_settle_ttg_read_brier_vs_total_bucket(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(Read(read_id="R-ttg", match_id=_MID, snapshot_id="S-spot",
                      made_at="t", judge="shadow", market="ttg",
                      prior=dict(_TTG_FAIR), belief=dict(_TTG_FAIR),
                      factors=[], confidence=1, shadow=True))
    n = settle_reads_for_matches(store, outcomes={_MID: ("home", "2:1")},
                                 settled_at="t2")
    assert n == 1
    s = store.settlement_for("read", "R-ttg")
    # Brier 靶 = total_3:Σ(p−onehot)² = (0.22−1)² + Σ其余 p²
    expected = sum((p - (1.0 if k == "total_3" else 0.0)) ** 2
                   for k, p in _TTG_FAIR.items())
    assert s.brier is not None and abs(s.brier - expected) < 1e-9


def test_backfill_creates_had_and_ttg_shadows(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_sporttery_snap())
    n = backfill_shadows(store, run_date="2026-07-08", made_at="t")
    assert n == 2                                              # had + ttg 各一条
    markets = sorted(r.market for r in store.load(Read) if r.shadow)
    assert markets == ["had", "ttg"]
    # 幂等
    assert backfill_shadows(store, run_date="2026-07-08", made_at="t") == 0


def test_backfill_no_ttg_fair_only_had_shadow(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(MarketSnapshot(
        snapshot_id="S-euro", match_id=_MID, taken_at="t",
        kind="read_time", source="apifootball",
        fair={"had": {"home": 0.45, "draw": 0.28, "away": 0.27}}))
    n = backfill_shadows(store, run_date="2026-07-08", made_at="t")
    assert n == 1
    assert [r.market for r in store.load(Read)] == ["had"]


def test_ingest_had_read_keeps_ttg_shadow(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(_sporttery_snap())
    backfill_shadows(store, run_date="2026-07-08", made_at="t")
    payload = {
        "read_id": "R-claude", "match_id": _MID, "snapshot_id": "S-spot",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.45, "draw": 0.28, "away": 0.27},
        "belief": {"home": 0.45, "draw": 0.28, "away": 0.27},
        "factors": [], "confidence": 3, "shadow": False,
    }
    errs = ingest_reads([payload], store=store, factors=[
        Factor("seeding_incentive", "签位", "d", "2026-06-27", "071", status="probation")])
    assert errs == []
    remaining = {(r.market, r.shadow) for r in store.load(Read)}
    # had shadow 被真判读顶掉;ttg shadow 保留
    assert remaining == {("had", False), ("ttg", True)}
