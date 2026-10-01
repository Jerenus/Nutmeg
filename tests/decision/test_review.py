import json
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.review import expected_return_ratio, prize_medians, review


def _leg(key, sels, odds, fair):
    return SlipLeg(key=key, name=key, market="had", line=None, selections=tuple(sels),
                   odds=tuple(odds), fair=fair)


FAIR_FAV = {"home": 0.75, "draw": 0.15, "away": 0.10}
FAIR_COIN = {"home": 0.40, "draw": 0.30, "away": 0.30}


def test_expected_return_ratio_jczq_parlay_and_veto_levels() -> None:
    fair_pair = BetSlip(slip_id="a", channel="jczq", placed_at="2026-10-02", combo_sizes=(2,),
                        legs=[_leg("周五001", ["home"], [1.20], FAIR_FAV),
                              _leg("周五002", ["home"], [2.20], FAIR_COIN)])
    ratio = expected_return_ratio(fair_pair, prize_median={})
    assert ratio == round(0.75 * 0.40 * 1.20 * 2.20 * 2 / 2, 3)        # 0.792 → info
    out = review(fair_pair, {"shared_naked": []}, prize_median={})
    assert out["vetoed"] is False and out["verdicts"][0]["level"] == "info"

    stacked = BetSlip(slip_id="b", channel="jczq", placed_at="2026-10-02", combo_sizes=(2,),
                      legs=[_leg("周五001", ["home", "draw"], [1.20, 6.0], FAIR_FAV),
                            _leg("周五002", ["home", "draw", "away"], [2.2, 3.1, 3.3], FAIR_COIN)])
    # 2×3=6 注 ¥12；P=0.9×1.0；模态赔率 1.20×2.20 → EV 4.75/12 = 0.40 → 否决
    out = review(stacked, {"shared_naked": []}, prize_median={})
    assert out["ratio"] < 0.5 and out["vetoed"] is True and out["verdicts"][0]["code"] == "V1"

    missing = BetSlip(slip_id="c", channel="jczq", placed_at="2026-10-02", combo_sizes=(2,),
                      legs=[_leg("周五001", ["home"], [1.20], None),
                            _leg("周五002", ["home"], [2.20], FAIR_COIN)])
    out = review(missing, {"shared_naked": []}, prize_median={})
    assert out["ratio"] is None and "未检" in out["verdicts"][0]["text"] and not out["vetoed"]


def test_shared_naked_legs_are_a_veto_and_multiplier_only_warns() -> None:
    slip = BetSlip(slip_id="d", channel="jczq", placed_at="2026-10-02", combo_sizes=(2,),
                   multiplier=20,
                   legs=[_leg("周五001", ["home"], [1.20], FAIR_FAV),
                         _leg("周五002", ["home"], [2.20], FAIR_COIN)])
    diagnosis = {"shared_naked": [{"key": "周五001", "face": "3", "slip_ids": ["d", "x"]}],
                 "joint_death": {"p_all_die_at_least": 0.25}}
    out = review(slip, diagnosis, prize_median={})
    codes = {(v["code"], v["level"]) for v in out["verdicts"]}
    assert ("V2", "veto") in codes and ("V3", "warn") in codes and out["vetoed"]
    assert any("联死 ≥25%" in line for line in out["lines"])


def test_zucai_ratio_uses_official_prize_median(tmp_path: Path) -> None:
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    (zdir / "official-prizes.json").write_text(json.dumps({"issues": {
        "26131": {"renjiu": {"stake_amount": 300.0}, "sfc_first": {"stake_amount": 10000.0}},
        "26132": {"renjiu": {"stake_amount": 4098.0}, "sfc_first": {"stake_amount": 50000.0}},
        "26133": {"renjiu": {"stake_amount": 5029.0}, "sfc_first": {"stake_amount": 2034299.0}},
    }}), encoding="utf-8")
    medians = prize_medians(tmp_path)
    assert medians == {"renjiu": 4098.0, "shengfucai": 50000.0}
    faces = {str(i): "3" for i in range(1, 10)}
    legs = [SlipLeg(key=str(i), market="had", selections=("home",), fair={"home": 0.5, "draw": 0.3,
                                                                          "away": 0.2})
            for i in range(1, 10)]
    slip = BetSlip(slip_id="r", channel="renjiu", placed_at="2026-10-02", legs=legs, faces=faces,
                   issue="26135")
    ratio = expected_return_ratio(slip, prize_median=medians)
    assert ratio == round(0.5 ** 9 * 4098.0 / 2, 3)                     # ≈ 4.0 → 热门裸单九连
    assert prize_medians(tmp_path / "nowhere") == {"renjiu": None, "shengfucai": None}
