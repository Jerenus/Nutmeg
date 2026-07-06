from nutmeg.decision.calibrate import render_panel, run_calibrate
from nutmeg.decision.ontology import FactorVerdict, Read, Settlement
from nutmeg.decision.store import DecisionStore


def _seed(store, n, factor_id, clv_hit_rate, brier_delta):
    hits = int(round(n * clv_hit_rate))
    for i in range(n):
        rid = f"R-{factor_id}-{i}"
        store.upsert(Read(read_id=rid, match_id=f"M-x-{i}", snapshot_id="s",
                          made_at="t", judge="claude", market="had",
                          prior={"home": 0.4, "draw": 0.3, "away": 0.3},
                          belief={"home": 0.5, "draw": 0.25, "away": 0.25},
                          factors=[{"factor_id": factor_id}]))
        # 预置 Settlement 携带 brier/clv（clv_hit 由 clv_pp>0 表征）
        store.upsert(Settlement(
            settlement_id=f"SET-read-{rid}", ref_type="read",
            ref_id=rid, settled_at="t", outcome_90="draw",
            brier=0.2 + brier_delta, clv_pp=(1.0 if i < hits else -1.0)))


def test_run_calibrate_produces_verdicts(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, 31, "seeding_incentive", clv_hit_rate=0.58, brier_delta=-0.01)
    verdicts = run_calibrate(store, as_of="2026-07-20")
    v = next(v for v in verdicts if v.factor_id == "seeding_incentive")
    assert v.n_reads == 31
    assert store.get(FactorVerdict, "seeding_incentive") is not None  # 落库


def test_render_panel_contains_factor_and_rates(tmp_path):
    store = DecisionStore(tmp_path)
    _seed(store, 31, "seeding_incentive", clv_hit_rate=0.58, brier_delta=-0.01)
    verdicts = run_calibrate(store, as_of="2026-07-20")
    panel = render_panel(verdicts)
    assert "seeding_incentive" in panel
    assert "CLV" in panel and "Brier" in panel
