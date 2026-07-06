from nutmeg.decision.ontology import MarketSnapshot, Read, Settlement
from nutmeg.decision.reconcile import settle_day
from nutmeg.decision.store import DecisionStore


def _seed(store, *, with_closing):
    store.upsert(Read(read_id="R-1", match_id="M-2026-07-08-周日092",
                      snapshot_id="S-r", made_at="t", judge="claude", market="had",
                      prior={"home": 0.42, "draw": 0.28, "away": 0.30},
                      belief={"home": 0.36, "draw": 0.34, "away": 0.30}))
    if with_closing:
        store.upsert(MarketSnapshot(
            snapshot_id="S-c", match_id="M-2026-07-08-周日092", taken_at="t2",
            kind="closing", source="apifootball",
            fair={"had": {"home": 0.34, "draw": 0.37, "away": 0.29}}))


def _results():
    # okooo 赛果口径:{竞彩号: {score, had, ...}}
    return {"周日092": {"score": "1:1", "had": "平"}}


def test_settle_day_scores_brier_and_clv(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    n = settle_day(store, run_date="2026-07-08", results=_results(),
                   settled_at="2026-07-09T08:00:00+08:00")
    assert n == 1
    s = store.settlement_for("read", "R-1")
    assert s is not None and s.outcome_90 == "draw"
    assert s.brier is not None and s.clv_pp is not None    # 双轴齐
    assert s.closing_snapshot_id == "S-c"


def test_settle_day_clv_null_without_closing(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=False)
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    s = store.settlement_for("read", "R-1")
    assert s.brier is not None and s.clv_pp is None        # 无收盘→CLV null


def test_settle_day_pending_when_no_result(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    settle_day(store, run_date="2026-07-08", results={}, settled_at="t")
    s = store.settlement_for("read", "R-1")
    assert s.brier is None and s.outcome_90 is None        # 赛果缺→pending


def test_settle_day_idempotent(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, with_closing=True)
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    settle_day(store, run_date="2026-07-08", results=_results(), settled_at="t")
    assert len([s for s in store.load(Settlement) if s.ref_id == "R-1"]) == 1
