# tests/decision/test_scoring.py
from nutmeg.decision.scoring import brier, brier_delta_vs_prior


def test_brier_perfect_and_worst():
    # 完美预测(把 1.0 给了发生的结果)→ 0
    assert brier({"home": 1.0, "draw": 0.0, "away": 0.0}, "home") == 0.0
    # 最差(把 1.0 给了没发生的)→ 2.0(两项各 1.0)
    assert brier({"home": 0.0, "draw": 0.0, "away": 1.0}, "home") == 2.0


def test_brier_uniform():
    # 均匀 1/3,结果 home:(1-1/3)^2 + (1/3)^2 + (1/3)^2 = 4/9+1/9+1/9 = 6/9
    b = brier({"home": 1/3, "draw": 1/3, "away": 1/3}, "home")
    assert abs(b - 6/9) < 1e-9


def test_brier_delta_negative_when_belief_better():
    prior = {"home": 0.33, "draw": 0.33, "away": 0.34}
    belief = {"home": 0.55, "draw": 0.25, "away": 0.20}   # 更看好 home
    # 结果 home → belief 更接近 → delta<0(改善)
    assert brier_delta_vs_prior(belief, prior, "home") < 0


