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


def test_new_seed_factors_are_backfilled_into_a_non_empty_store(tmp_path):
    """种子新增的因子必须能进已有 store，否则是死码。

    ``seed_factors_if_empty`` 只在 store 为空时播种，``sync_factor_scopes`` 只改
    scope。2026-09-14 加 price_drift/book_dispersion/vig_shift 时就踩到这个洞：
    三个因子躺在种子 JSON 里，store 没有，于是 ``allowed_factor_ids`` 拒绝任何引用
    它们的 Read——注册了却永远用不上。
    """
    from nutmeg.decision.calibrate import backfill_missing_seed_factors
    from nutmeg.decision.factors import allowed_factor_ids

    s = DecisionStore(tmp_path)
    seed = load_seed_factors()
    for f in seed[:-1]:              # 故意少播最后一个
        s.upsert(f)
    assert backfill_missing_seed_factors(s) == 1
    assert backfill_missing_seed_factors(s) == 0        # 幂等
    assert allowed_factor_ids(s.load(Factor)) >= {f.factor_id for f in seed}


def test_backfill_never_resurrects_a_retired_factor(tmp_path):
    """已退休的因子留在 store 里且状态是 retired——补种不得把它改回 probation。"""
    from dataclasses import replace

    from nutmeg.decision.calibrate import backfill_missing_seed_factors

    s = DecisionStore(tmp_path)
    seed = load_seed_factors()
    for f in seed:
        s.upsert(f)
    dead = replace(seed[0], status="retired", retire_reason="双轴平庸")
    s.upsert(dead)

    assert backfill_missing_seed_factors(s) == 0        # 它在 store 里，不是缺失
    assert s.get(Factor, seed[0].factor_id).status == "retired"
