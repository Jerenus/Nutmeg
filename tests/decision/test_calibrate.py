# tests/decision/test_calibrate.py
from nutmeg.decision.calibrate import enforce_active_cap, factor_verdict
from nutmeg.decision.ontology import Factor, FactorVerdict


def _settlements(n, clv_hit_rate, brier_delta):
    """构造 n 条已结 Settlement dict(简化:直接给聚合前的单条值)。"""
    out = []
    hits = int(round(n * clv_hit_rate))
    for i in range(n):
        out.append({"brier_delta": brier_delta,
                    "clv_hit": 1 if i < hits else 0})
    return out


def test_probation_when_under_30():
    v = factor_verdict("seeding_incentive", _settlements(20, 0.7, -0.02),
                       as_of="2026-07-20")
    assert v.recommendation == "keep"          # n<30 只积累不判决
    assert v.n_reads == 20


def test_active_when_double_axis_good():
    v = factor_verdict("seeding_incentive", _settlements(31, 0.58, -0.01),
                       as_of="2026-07-20")
    assert v.recommendation == "keep"          # CLV>0.55 且 brier_delta<0
    assert abs(v.clv_hit_rate - 18/31) < 0.02


def test_retire_when_double_axis_mediocre():
    v = factor_verdict("bad_factor", _settlements(31, 0.45, 0.02),
                       as_of="2026-07-20")
    assert v.recommendation == "retire"        # CLV<0.55 且 brier_delta>0


def test_watch_when_mixed():
    v = factor_verdict("mixed", _settlements(31, 0.58, 0.02),
                       as_of="2026-07-20")
    assert v.recommendation == "watch"         # 一轴好一轴差


def test_enforce_cap_retires_weakest_when_over_limit():
    # 13 个 active,超 12 → 最弱(clv 最低)被退休
    factors = [Factor(f"f{i}", f"F{i}", "d", "2026-07-06", "x", status="active")
               for i in range(13)]
    verdicts = [FactorVerdict(f"f{i}", "2026-07-20", 31, -0.01, 0.50 + i * 0.01,
                              0.55, "keep") for i in range(13)]
    retired = enforce_active_cap(factors, verdicts)
    assert retired == ["f0"]                    # clv 最低者


def test_run_calibrate_emits_diagnostic_subverdicts_per_scope_key(tmp_path):
    """带 scope_key 的引用 → 额外产 factor_id@scope_key 诊断子判决(证据分辨率,
    非生死状态机——提案 2026-07-07 复核修正)。复合 id 亦防 store clobber。"""
    from nutmeg.decision.calibrate import run_calibrate
    from nutmeg.decision.ontology import Read, Settlement
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    store.upsert(Read(
        read_id="R-1", match_id="M-1", snapshot_id="S-1", made_at="t",
        judge="claude", market="had",
        prior={"home": 0.5, "draw": 0.3, "away": 0.2},
        belief={"home": 0.44, "draw": 0.36, "away": 0.2},
        factors=[{"factor_id": "league_bias", "scope_key": "swe-allsvenskan",
                  "direction": "draw", "weight_pp": 6,
                  "evidence": [{"url": "u"}]}]))
    store.upsert(Settlement(
        settlement_id="SET-read-R-1", ref_type="read", ref_id="R-1",
        settled_at="t", outcome_90="draw", brier=0.6, clv_pp=0.01))
    verdicts = {v.factor_id: v for v in run_calibrate(store, as_of="2026-07-07")}
    assert "league_bias" in verdicts                       # 生死判决主体不变
    assert "league_bias@swe-allsvenskan" in verdicts       # 诊断子判决
    assert verdicts["league_bias@swe-allsvenskan"].recommendation == "diagnostic"
    assert verdicts["league_bias"].recommendation == "keep"   # n=1<30 只积累
    assert verdicts["league_bias@swe-allsvenskan"].n_reads == 1


def test_apply_verdicts_ignores_diagnostic_subverdicts(tmp_path):
    """子判决永不驱动转正/退休——生死留在 factor 级(反 churn n≥30 不变)。"""
    from nutmeg.decision.calibrate import apply_verdicts, seed_factors_if_empty
    from nutmeg.decision.ontology import Factor, FactorVerdict
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    seed_factors_if_empty(store)
    sub = FactorVerdict(
        factor_id="league_bias@swe-allsvenskan", as_of="2026-07-07",
        n_reads=40, brier_delta_vs_prior=-0.1, clv_hit_rate=0.9,
        direction_hit_rate=None, recommendation="diagnostic")
    changes = apply_verdicts(store, [sub])
    assert changes == {"promoted": [], "retired": []}
    fac = {f.factor_id: f for f in store.load(Factor)}["league_bias"]
    assert fac.status == "probation"                       # 不受子判决影响
