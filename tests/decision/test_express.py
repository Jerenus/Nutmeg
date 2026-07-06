# tests/decision/test_express.py
from nutmeg.decision.express import (
    load_budget,
    parlay_odds,
    renjiu_ticket_count,
    within_budget,
)


def test_budget_buckets_from_config():
    b = load_budget()
    assert b["jczq"]["had_modal"] == 100
    assert b["jczq"]["draw_single"] == 40
    assert b["shengfucai_renjiu"]["fushi"] == 400


def test_renjiu_count_is_2002():
    # 任九 = 从 14 场选 9 场命中(C(14,9)) = 2002
    assert renjiu_ticket_count(14, 9) == 2002


def test_parlay_odds_multiplies():
    assert abs(parlay_odds([1.64, 2.75]) - 4.51) < 1e-9


def test_within_budget_gate():
    assert within_budget("jczq", "had_modal", 80) is True
    assert within_budget("jczq", "had_modal", 120) is False   # 超 ¥100
