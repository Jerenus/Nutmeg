# tests/decision/test_reconcile.py
from nutmeg.decision.ontology import MarketSnapshot, Read
from nutmeg.decision.reconcile import settle_read


def _read(belief):
    return Read(read_id="R-1", match_id="M-1", snapshot_id="S-1", made_at="t",
                judge="claude", market="had",
                prior={"home": 0.46, "draw": 0.27, "away": 0.27},
                belief=belief, confidence=3, shadow=False)


def _closing(fair):
    return MarketSnapshot(snapshot_id="S-close", match_id="M-1", taken_at="t2",
                          kind="closing", source="okooo_sp", fair={"had": fair})


def test_settle_read_scores_both_axes():
    read = _read({"home": 0.40, "draw": 0.33, "away": 0.27})
    closing = _closing({"home": 0.34, "draw": 0.37, "away": 0.29})
    s = settle_read(read, outcome_90="draw", score="1-1", closing=closing)
    assert s.ref_type == "read" and s.ref_id == "R-1"
    assert s.brier is not None and s.clv_pp is not None
    assert s.closing_snapshot_id == "S-close"
    assert s.outcome_90 == "draw"


def test_settle_read_pending_when_no_result():
    read = _read({"home": 0.40, "draw": 0.33, "away": 0.27})
    s = settle_read(read, outcome_90=None, score=None, closing=_closing(
        {"home": 0.34, "draw": 0.37, "away": 0.29}))
    assert s.brier is None and s.outcome_90 is None


def test_settle_read_clv_null_when_no_closing():
    read = _read({"home": 0.40, "draw": 0.33, "away": 0.27})
    s = settle_read(read, outcome_90="draw", score="1-1", closing=None)
    assert s.brier is not None       # 赛果有→Brier 有
    assert s.clv_pp is None          # 无收盘→CLV=null(绝不伪造)


def test_settle_shadow_read_still_scores_brier():
    shadow = Read(read_id="R-2", match_id="M-1", snapshot_id="S-1", made_at="t",
                  judge="claude", market="had",
                  prior={"home": 0.46, "draw": 0.27, "away": 0.27},
                  belief={"home": 0.46, "draw": 0.27, "away": 0.27}, shadow=True)
    s = settle_read(shadow, outcome_90="home", score="2-0", closing=None)
    assert s.brier is not None and s.clv_pp is None
