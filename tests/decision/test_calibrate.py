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
