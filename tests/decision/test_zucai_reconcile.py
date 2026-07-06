# tests/decision/test_zucai_reconcile.py
from nutmeg.decision.ontology import Read
from nutmeg.decision.reconcile import settle_reads_for_matches
from nutmeg.decision.store import DecisionStore


def test_settle_reads_by_match_id_with_1x2_result(tmp_path):
    s = DecisionStore(tmp_path)
    mid = "M-2026-07-06-阿根廷-埃及"
    s.upsert(Read(read_id="R-z1", match_id=mid, snapshot_id="S", made_at="t",
                  judge="claude", market="had",
                  prior={"home": 0.7, "draw": 0.2, "away": 0.1},
                  belief={"home": 0.75, "draw": 0.18, "away": 0.07}))
    # 结果按 canonical match_id → outcome
    n = settle_reads_for_matches(s, outcomes={mid: ("home", "2-0")},
                                 settled_at="t2")
    assert n == 1
    st = s.settlement_for("read", "R-z1")
    assert st.outcome_90 == "home" and st.brier is not None


def test_settle_reads_skips_reads_without_result(tmp_path):
    """无结果的 Read 跳过(不 clobber 既有/pending 结算)——canonical 混库安全。"""
    s = DecisionStore(tmp_path)
    graded = "M-2026-07-06-阿根廷-埃及"
    other = "M-2026-07-06-葡萄牙-西班牙"
    for rid, mid in (("R-z1", graded), ("R-j2", other)):
        s.upsert(Read(read_id=rid, match_id=mid, snapshot_id="S", made_at="t",
                      judge="claude", market="had",
                      prior={"home": 0.5, "draw": 0.3, "away": 0.2},
                      belief={"home": 0.5, "draw": 0.3, "away": 0.2}))
    n = settle_reads_for_matches(s, outcomes={graded: ("home", "1-0")},
                                 settled_at="t2")
    assert n == 1                                    # 只结算有结果的那条
    assert s.settlement_for("read", "R-z1") is not None
    assert s.settlement_for("read", "R-j2") is None  # 无结果场未被 clobber
