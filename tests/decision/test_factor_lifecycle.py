"""因子生死机制的执行(反积累免疫落地):verdict → Factor 状态转换 + 持久化。"""
from nutmeg.decision.calibrate import apply_verdicts, seed_factors_if_empty
from nutmeg.decision.factors import load_seed_factors
from nutmeg.decision.ontology import Factor, FactorVerdict
from nutmeg.decision.store import DecisionStore


def _v(fid, rec, n=31):
    return FactorVerdict(factor_id=fid, as_of="2026-07-20", n_reads=n,
                         brier_delta_vs_prior=-0.01, clv_hit_rate=0.58,
                         direction_hit_rate=0.55, recommendation=rec)


def test_seed_factors_idempotent(tmp_path):
    s = DecisionStore(tmp_path)
    seeded = seed_factors_if_empty(s)
    assert seeded == len(load_seed_factors())
    assert seed_factors_if_empty(s) == 0            # 幂等
    assert len(s.load(Factor)) == seeded


def test_retire_verdict_sets_status_retired(tmp_path):
    s = DecisionStore(tmp_path)
    seed_factors_if_empty(s)
    apply_verdicts(s, [_v("seeding_incentive", "retire")])
    f = s.get(Factor, "seeding_incentive")
    assert f.status == "retired" and "平庸" in f.retire_reason


def test_keep_verdict_promotes_probation_to_active(tmp_path):
    s = DecisionStore(tmp_path)
    seed_factors_if_empty(s)
    r = apply_verdicts(s, [_v("bunker_profile", "keep", n=31)])
    assert "bunker_profile" in r["promoted"]
    assert s.get(Factor, "bunker_profile").status == "active"


def test_under_30_keep_stays_probation(tmp_path):
    s = DecisionStore(tmp_path)
    seed_factors_if_empty(s)
    apply_verdicts(s, [_v("league_bias", "keep", n=20)])   # n<30
    assert s.get(Factor, "league_bias").status == "probation"


def test_retired_factor_rejected_by_read_validate_after_apply(tmp_path):
    from nutmeg.decision.factors import allowed_factor_ids
    s = DecisionStore(tmp_path)
    seed_factors_if_empty(s)
    apply_verdicts(s, [_v("fatigue_discount", "retire")])
    allowed = allowed_factor_ids(s.load(Factor))
    assert "fatigue_discount" not in allowed        # 退休后 read 校验即拒
