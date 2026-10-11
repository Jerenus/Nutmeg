import json
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.review import (
    expected_return_ratio,
    prize_medians,
    prize_model,
    review,
    zucai_return,
)


def _leg(key, sels, odds, fair):
    return SlipLeg(key=key, name=key, market="had", line=None, selections=tuple(sels),
                   odds=tuple(odds), fair=fair)


FAIR_FAV = {"home": 0.75, "draw": 0.15, "away": 0.10}
FAIR_COIN = {"home": 0.40, "draw": 0.30, "away": 0.30}


def test_expected_return_ratio_jczq_parlay_and_veto_levels() -> None:
    fair_pair = BetSlip(slip_id="a", channel="jczq", placed_at="2026-10-02", combo_sizes=(2,),
                        legs=[_leg("周五001", ["home"], [1.20], FAIR_FAV),
                              _leg("周五002", ["home"], [2.20], FAIR_COIN)])
    ratio = expected_return_ratio(fair_pair, prize_model={})
    assert ratio == round(0.75 * 0.40 * 1.20 * 2.20 * 2 / 2, 3)        # 0.792 → info
    out = review(fair_pair, {"shared_naked": []}, prize_model={})
    assert out["vetoed"] is False and out["verdicts"][0]["level"] == "info"

    stacked = BetSlip(slip_id="b", channel="jczq", placed_at="2026-10-02", combo_sizes=(2,),
                      legs=[_leg("周五001", ["home", "draw"], [1.20, 6.0], FAIR_FAV),
                            _leg("周五002", ["home", "draw", "away"], [2.2, 3.1, 3.3], FAIR_COIN)])
    # 2×3=6 注 ¥12；P=0.9×1.0；模态赔率 1.20×2.20 → EV 4.75/12 = 0.40 → 否决
    out = review(stacked, {"shared_naked": []}, prize_model={})
    assert out["ratio"] < 0.5 and out["vetoed"] is True and out["verdicts"][0]["code"] == "V1"

    missing = BetSlip(slip_id="c", channel="jczq", placed_at="2026-10-02", combo_sizes=(2,),
                      legs=[_leg("周五001", ["home"], [1.20], None),
                            _leg("周五002", ["home"], [2.20], FAIR_COIN)])
    out = review(missing, {"shared_naked": []}, prize_model={})
    assert out["ratio"] is None and "未检" in out["verdicts"][0]["text"] and not out["vetoed"]


def test_shared_naked_legs_are_a_veto_and_multiplier_only_warns() -> None:
    slip = BetSlip(slip_id="d", channel="jczq", placed_at="2026-10-02", combo_sizes=(2,),
                   multiplier=20,
                   legs=[_leg("周五001", ["home"], [1.20], FAIR_FAV),
                         _leg("周五002", ["home"], [2.20], FAIR_COIN)])
    diagnosis = {"shared_naked": [{"key": "周五001", "face": "3", "slip_ids": ["d", "x"]}],
                 "joint_death": {"p_all_die_at_least": 0.25}}
    out = review(slip, diagnosis, prize_model={})
    codes = {(v["code"], v["level"]) for v in out["verdicts"]}
    assert ("V2", "veto") in codes and ("V3", "warn") in codes and out["vetoed"]
    assert any("联死 ≥25%" in line for line in out["lines"])


def test_zucai_ratio_falls_back_to_official_prize_median(tmp_path: Path) -> None:
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "official-prizes.json").write_text(json.dumps({"issues": {
        "26131": {"renjiu": {"stake_amount": 300.0}, "sfc_first": {"stake_amount": 10000.0}},
        "26132": {"renjiu": {"stake_amount": 4098.0}, "sfc_first": {"stake_amount": 50000.0}},
        "26133": {"renjiu": {"stake_amount": 5029.0}, "sfc_first": {"stake_amount": 2034299.0}},
    }}), encoding="utf-8")
    medians = prize_medians(tmp_path)
    assert medians == {"renjiu": 4098.0, "shengfucai": 50000.0}
    model = prize_model(tmp_path)                       # 无 prize-model.json → 只有中位数
    assert model == {"renjiu": {"median": 4098.0}, "shengfucai": {"median": 50000.0}}
    faces = {str(i): "3" for i in range(1, 10)}
    legs = [SlipLeg(key=str(i), market="had", selections=("home",), fair={"home": 0.5, "draw": 0.3,
                                                                          "away": 0.2})
            for i in range(1, 10)]
    slip = BetSlip(slip_id="r", channel="renjiu", placed_at="2026-10-02", legs=legs, faces=faces,
                   issue="26135")
    ratio = expected_return_ratio(slip, prize_model=model)
    assert ratio == round(0.5 ** 9 * 4098.0 / 2, 3)                     # ≈ 4.0 → 热门裸单九连
    out = review(slip, {"shared_naked": []}, prize_model=model)
    assert "中位数口径" in out["verdicts"][0]["text"]
    assert prize_medians(tmp_path / "nowhere") == {"renjiu": None, "shengfucai": None}


def _zucai_slip(fair: dict, faces_str: str = "3") -> BetSlip:
    legs = [SlipLeg(key=str(i), market="had",
                    selections=tuple({"3": "home", "1": "draw", "0": "away"}[c] for c in faces_str),
                    fair=fair) for i in range(1, 10)]
    return BetSlip(slip_id="m", channel="renjiu", placed_at="2026-10-02", legs=legs,
                   faces={str(i): faces_str for i in range(1, 10)}, issue="26135")


def test_zucai_return_model_is_flat_under_market_and_pays_a_premium_for_belief() -> None:
    # b = 1：市场口径下任何票面每元期望都一样（= e^{a+sd²/2}·3^5/2），形状不改变 EV
    model = {"renjiu": {"median": 3774.0, "a": -5.2547, "b": 1.0, "resid_sd": 0.62}}
    market = {str(i): {"home": 0.5, "draw": 0.3, "away": 0.2} for i in range(1, 15)}
    single = zucai_return(_zucai_slip(market["1"], "3"), model=model, market=market)
    double = zucai_return(_zucai_slip(market["1"], "31"), model=model, market=market)
    assert single["basis"] == "model" and single["premium"] == 1.0 and double["premium"] == 1.0
    assert single["ratio_market"] == double["ratio_market"] == single["ratio"]
    flat = round(__import__("math").exp(-5.2547 + 0.62 ** 2 / 2) * 3 ** 5 / 2, 3)
    assert single["ratio"] == flat and 0.7 < flat < 0.9
    # 判断把 0.5 的主胜看成 0.6：每腿溢价 1.2，九腿 → 1.2^9
    belief = {"home": 0.6, "draw": 0.25, "away": 0.15}
    tilted = zucai_return(_zucai_slip(belief, "3"), model=model, market=market)
    assert abs(tilted["premium"] - round(1.2 ** 9, 3)) < 0.01
    assert abs(tilted["ratio"] - round(flat * 1.2 ** 9, 3)) < 0.05
    # 判断反向（0.4）→ 溢价 0.8^9 ≈ 0.13 → 期望回报 < 0.5 → V1 否决
    against = {"home": 0.4, "draw": 0.35, "away": 0.25}
    out = review(_zucai_slip(against, "3"), {"shared_naked": []}, prize_model=model,
                 market=market)
    assert out["vetoed"] and out["verdicts"][0]["code"] == "V1"
    assert "判断溢价 0.13" in out["verdicts"][0]["text"]
    # 缺市场分布：未选的 5 场按均匀 1/3 → 3^b 同一常数（b=1 时结果不变）
    assert zucai_return(_zucai_slip(market["1"], "3"), model=model)["ratio"] == flat


def test_v4_vetoes_renjiu_with_more_than_nine_matches() -> None:
    """2026-10-12：任九 >9 场的容错复式渠道不可购，预审否决（注数算法本身支持 >9 场）。"""
    ten = {str(i): "3" for i in range(1, 11)}
    slip = BetSlip(slip_id="r10", channel="renjiu", placed_at="2026-10-12", legs=[],
                   issue="26139", faces=ten)
    assert slip.notes == 10
    out = review(slip, {"shared_naked": []}, prize_model={})
    codes = {v["code"]: v["level"] for v in out["verdicts"]}
    assert codes.get("V4") == "veto" and out["vetoed"] is True
    nine = BetSlip(slip_id="r9", channel="renjiu", placed_at="2026-10-12", legs=[],
                   issue="26139", faces={k: ten[k] for k in list(ten)[:9]})
    out9 = review(nine, {"shared_naked": []}, prize_model={})
    assert "V4" not in {v["code"] for v in out9["verdicts"]}
