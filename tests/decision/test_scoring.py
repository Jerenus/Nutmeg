# tests/decision/test_scoring.py
from nutmeg.decision.scoring import brier, brier_delta_vs_prior, clv_pp


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


def test_clv_pp_positive_when_moved_toward_closing():
    prior = {"home": 0.40, "draw": 0.30, "away": 0.30}
    belief = {"home": 0.46, "draw": 0.27, "away": 0.27}    # 朝 home 偏
    closing = {"home": 0.50, "draw": 0.28, "away": 0.22}   # 收盘也朝 home
    assert clv_pp(belief, prior, closing) > 0               # 偏移方向对


def test_clv_pp_negative_when_moved_against_closing():
    prior = {"home": 0.40, "draw": 0.30, "away": 0.30}
    belief = {"home": 0.46, "draw": 0.27, "away": 0.27}    # 朝 home 偏
    closing = {"home": 0.34, "draw": 0.33, "away": 0.33}   # 收盘反朝 away
    assert clv_pp(belief, prior, closing) < 0
