# tests/decision/test_market_data.py
from nutmeg.decision.market_data import devig, fair_1x2


def test_devig_normalizes_to_one():
    fair = devig({"home": 2.0, "draw": 4.0, "away": 4.0})
    assert abs(sum(fair.values()) - 1.0) < 1e-9
    assert fair["home"] > fair["draw"]          # 短赔=高概率


def test_devig_empty_input():
    assert devig({}) == {}
    assert devig({"home": 0.0}) == {}


def test_fair_1x2_hard_keyed():
    fair = fair_1x2({"home": 2.03, "draw": 3.30, "away": 3.55})
    assert set(fair) == {"home", "draw", "away"}
    assert abs(sum(fair.values()) - 1.0) < 1e-6
